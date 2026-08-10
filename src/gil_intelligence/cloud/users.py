from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from threading import Lock
from typing import Any


@dataclass(slots=True)
class UserApiError(Exception):
    status: HTTPStatus
    code: str
    detail: str | None = None

    def __str__(self) -> str:
        return self.detail or self.code


class FirebaseUserService:
    """Authenticated user state backed by Firebase Auth and Cloud Firestore.

    Firebase imports and clients are initialized lazily so the public market API can
    still start in local environments where authentication is intentionally disabled.
    """

    def __init__(
        self,
        *,
        project_id: str,
        bootstrap_admin_email: str,
        collection_name: str = "cactuar_users",
        invitation_collection_name: str | None = None,
    ) -> None:
        self.project_id = project_id
        self.bootstrap_admin_email = bootstrap_admin_email.strip().casefold()
        self.collection_name = collection_name
        self.invitation_collection_name = (
            invitation_collection_name or f"{collection_name}_invitations"
        )
        self._auth: Any = None
        self._firestore: Any = None
        self._database: Any = None
        self._initialize_lock = Lock()

    def register(self, authorization: str | None) -> dict[str, Any]:
        identity = self._identity(authorization)
        email = str(identity.get("email") or "").strip()
        provider = (identity.get("firebase") or {}).get("sign_in_provider")
        if not email or not identity.get("email_verified") or provider != "google.com":
            raise UserApiError(
                HTTPStatus.FORBIDDEN,
                "google_account_required",
                "Se requiere una cuenta Google con correo verificado.",
            )
        uid = identity["uid"]
        reference = self._users().document(uid)
        existing_snapshot = reference.get()
        existing = existing_snapshot.to_dict() if existing_snapshot.exists else None
        now = datetime.now(timezone.utc)
        is_bootstrap_admin = email.casefold() == self.bootstrap_admin_email
        invitation_reference = self._invitation_reference(email)
        invitation_snapshot = invitation_reference.get()
        is_preapproved = invitation_snapshot.exists
        if existing is None:
            profile = {
                "uid": uid,
                "email": email,
                "displayName": identity.get("name") or email.split("@", 1)[0],
                "photoURL": identity.get("picture"),
                "status": "ACTIVE" if is_bootstrap_admin or is_preapproved else "PENDING",
                "role": "ADMIN" if is_bootstrap_admin else "USER",
                "createdAt": now,
                "lastLoginAt": now,
            }
            reference.set(profile)
        else:
            profile = {
                **existing,
                "uid": uid,
                "email": email,
                "displayName": identity.get("name") or existing.get("displayName") or email,
                "photoURL": identity.get("picture") or existing.get("photoURL"),
                "lastLoginAt": now,
            }
            if is_bootstrap_admin:
                profile.update({"status": "ACTIVE", "role": "ADMIN"})
            elif is_preapproved and profile.get("status") == "PENDING":
                profile["status"] = "ACTIVE"
            reference.set(profile, merge=True)
        if is_preapproved:
            invitation_reference.delete()
        expected_claims = {
            "admin": profile.get("role") == "ADMIN",
            "approved": profile.get("status") == "ACTIVE",
        }
        if any(identity.get(key) != value for key, value in expected_claims.items()):
            self._sync_claims(uid, profile)
        return self._public_profile(profile)

    def me(self, authorization: str | None) -> dict[str, Any]:
        identity, profile = self._authorized_profile(authorization, allow_pending=True)
        return {
            **self._public_profile(profile),
            "emailVerified": bool(identity.get("email_verified")),
        }

    def authorize(self, authorization: str | None) -> dict[str, Any]:
        """Require an approved account before serving protected market data."""
        _, profile = self._authorized_profile(authorization)
        return self._public_profile(profile)

    def favorites(self, authorization: str | None) -> list[dict[str, Any]]:
        _, profile = self._authorized_profile(authorization)
        documents = self._users().document(profile["uid"]).collection("favorites").stream()
        favorites = []
        for document in documents:
            favorite = document.to_dict() or {}
            history = [
                observation.to_dict() or {}
                for observation in document.reference.collection("history").stream()
            ]
            favorite["history"] = sorted(
                (self._serialize(observation) for observation in history),
                key=lambda item: str(item.get("observedAt") or ""),
            )[-180:]
            favorites.append(self._serialize(favorite))
        return sorted(favorites, key=lambda item: str(item.get("addedAt") or ""), reverse=True)

    def put_favorite(
        self,
        authorization: str | None,
        key: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        _, profile = self._authorized_profile(authorization)
        normalized_key = self._validate_favorite_key(key)
        safe_metadata = self._favorite_metadata(metadata)
        reference = self._favorite_reference(profile["uid"], normalized_key)
        existing_snapshot = reference.get()
        existing = existing_snapshot.to_dict() if existing_snapshot.exists else {}
        now = datetime.now(timezone.utc)
        favorite = {
            **existing,
            **safe_metadata,
            "key": normalized_key,
            "module": safe_metadata.get("module") or normalized_key.split(":", 1)[0],
            "addedAt": existing.get("addedAt") or now,
            "updatedAt": now,
        }
        reference.set(favorite)
        return self._serialize(favorite)

    def delete_favorite(self, authorization: str | None, key: str) -> None:
        _, profile = self._authorized_profile(authorization)
        normalized_key = self._validate_favorite_key(key)
        reference = self._favorite_reference(profile["uid"], normalized_key)
        for observation in reference.collection("history").stream():
            observation.reference.delete()
        reference.delete()

    def record_favorite_observations(
        self,
        *,
        dashboard: dict[str, Any],
        market_items: dict[str, Any],
        opportunities: dict[str, Any],
        signals: dict[str, Any],
    ) -> dict[str, int]:
        """Persist one idempotent market point per favorite after a successful refresh."""
        observed_at = str(market_items.get("meta", {}).get("marketCollectedAt") or "")
        market_snapshot_id = str(signals.get("meta", {}).get("marketSnapshotId") or "")
        if not observed_at or not market_snapshot_id:
            raise ValueError("Favorite observations require a market timestamp and snapshot id")
        context = _favorite_observation_context(
            dashboard=dashboard,
            market_items=market_items,
            opportunities=opportunities,
            signals=signals,
        )
        observation_id = hashlib.sha256(market_snapshot_id.encode("utf-8")).hexdigest()
        watched = 0
        recorded = 0
        for user_snapshot in self._users().stream():
            favorites = user_snapshot.reference.collection("favorites").stream()
            for favorite_snapshot in favorites:
                watched += 1
                favorite = favorite_snapshot.to_dict() or {}
                observation = _favorite_observation(
                    favorite,
                    context=context,
                    market_snapshot_id=market_snapshot_id,
                    observed_at=observed_at,
                )
                if observation is None:
                    continue
                favorite_snapshot.reference.collection("history").document(observation_id).set(
                    observation
                )
                recorded += 1
        return {"watched": watched, "recorded": recorded}

    def list_users(self, authorization: str | None) -> list[dict[str, Any]]:
        self._authorized_profile(authorization, require_admin=True)
        result: list[dict[str, Any]] = []
        for snapshot in self._users().stream():
            profile = snapshot.to_dict() or {}
            favorite_count = sum(
                1 for _ in self._users().document(snapshot.id).collection("favorites").stream()
            )
            result.append({**self._public_profile(profile), "favoriteCount": favorite_count})
        return sorted(
            result,
            key=lambda item: (
                {"PENDING": 0, "ACTIVE": 1, "SUSPENDED": 2}.get(item["status"], 3),
                str(item.get("email") or "").casefold(),
            ),
        )

    def list_invitations(self, authorization: str | None) -> list[dict[str, Any]]:
        self._authorized_profile(authorization, require_admin=True)
        invitations = [
            self._public_invitation(snapshot.id, snapshot.to_dict() or {})
            for snapshot in self._invitations().stream()
        ]
        return sorted(invitations, key=lambda item: str(item.get("email") or "").casefold())

    def grant_access(self, authorization: str | None, email: str) -> dict[str, Any]:
        _, admin_profile = self._authorized_profile(authorization, require_admin=True)
        normalized_email = self._validate_email(email)
        now = datetime.now(timezone.utc)
        for snapshot in self._users().stream():
            profile = snapshot.to_dict() or {}
            if str(profile.get("email") or "").strip().casefold() != normalized_email:
                continue
            profile.update(
                {
                    "uid": snapshot.id,
                    "status": "ACTIVE",
                    "updatedAt": now,
                    "updatedBy": admin_profile["uid"],
                }
            )
            snapshot.reference.set(profile, merge=True)
            self._invitation_reference(normalized_email).delete()
            self._sync_claims(snapshot.id, profile)
            self._auth.update_user(snapshot.id, disabled=False)
            return {"kind": "USER", "user": self._public_profile(profile)}

        invitation_id = hashlib.sha256(normalized_email.encode("utf-8")).hexdigest()
        reference = self._invitations().document(invitation_id)
        existing_snapshot = reference.get()
        existing = existing_snapshot.to_dict() if existing_snapshot.exists else {}
        invitation = {
            **existing,
            "email": normalized_email,
            "createdAt": existing.get("createdAt") or now,
            "updatedAt": now,
            "updatedBy": admin_profile["uid"],
        }
        reference.set(invitation)
        return {
            "kind": "INVITATION",
            "invitation": self._public_invitation(invitation_id, invitation),
        }

    def revoke_invitation(self, authorization: str | None, invitation_id: str) -> None:
        self._authorized_profile(authorization, require_admin=True)
        normalized_id = str(invitation_id or "").strip().casefold()
        if len(normalized_id) != 64 or any(
            character not in "0123456789abcdef" for character in normalized_id
        ):
            raise UserApiError(HTTPStatus.BAD_REQUEST, "invalid_invitation_id")
        reference = self._invitations().document(normalized_id)
        if not reference.get().exists:
            raise UserApiError(HTTPStatus.NOT_FOUND, "invitation_not_found")
        reference.delete()

    def update_user(
        self,
        authorization: str | None,
        uid: str,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        identity, admin_profile = self._authorized_profile(authorization, require_admin=True)
        if not uid or len(uid) > 128:
            raise UserApiError(HTTPStatus.BAD_REQUEST, "invalid_uid")
        reference = self._users().document(uid)
        snapshot = reference.get()
        if not snapshot.exists:
            raise UserApiError(HTTPStatus.NOT_FOUND, "user_not_found")
        profile = snapshot.to_dict() or {}
        status = str(changes.get("status") or profile.get("status") or "PENDING").upper()
        role = str(changes.get("role") or profile.get("role") or "USER").upper()
        if status not in {"PENDING", "ACTIVE", "SUSPENDED"}:
            raise UserApiError(HTTPStatus.BAD_REQUEST, "invalid_status")
        if role not in {"USER", "ADMIN"}:
            raise UserApiError(HTTPStatus.BAD_REQUEST, "invalid_role")
        if uid == identity["uid"] and (status != "ACTIVE" or role != "ADMIN"):
            raise UserApiError(
                HTTPStatus.CONFLICT,
                "cannot_lock_current_admin",
                "No puedes suspenderte ni quitarte tu propio rol administrador.",
            )
        profile.update(
            {
                "uid": uid,
                "status": status,
                "role": role,
                "updatedAt": datetime.now(timezone.utc),
                "updatedBy": admin_profile["uid"],
            }
        )
        reference.set(profile, merge=True)
        if profile.get("email"):
            self._invitation_reference(str(profile["email"])).delete()
        self._sync_claims(uid, profile)
        self._auth.update_user(uid, disabled=status == "SUSPENDED")
        return self._public_profile(profile)

    def _identity(self, authorization: str | None) -> dict[str, Any]:
        if not authorization or not authorization.startswith("Bearer "):
            raise UserApiError(HTTPStatus.UNAUTHORIZED, "authentication_required")
        token = authorization[7:].strip()
        if not token:
            raise UserApiError(HTTPStatus.UNAUTHORIZED, "authentication_required")
        self._initialize()
        try:
            identity = self._auth.verify_id_token(token, check_revoked=True)
        except Exception as exc:
            raise UserApiError(HTTPStatus.UNAUTHORIZED, "invalid_token") from exc
        if not identity.get("uid"):
            raise UserApiError(HTTPStatus.UNAUTHORIZED, "invalid_token")
        return identity

    def _authorized_profile(
        self,
        authorization: str | None,
        *,
        allow_pending: bool = False,
        require_admin: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        identity = self._identity(authorization)
        snapshot = self._users().document(identity["uid"]).get()
        if not snapshot.exists:
            raise UserApiError(HTTPStatus.FORBIDDEN, "registration_required")
        profile = snapshot.to_dict() or {}
        status = profile.get("status")
        if status == "SUSPENDED":
            raise UserApiError(HTTPStatus.FORBIDDEN, "account_suspended")
        if not allow_pending and status != "ACTIVE":
            raise UserApiError(HTTPStatus.FORBIDDEN, "account_pending")
        if require_admin and profile.get("role") != "ADMIN":
            raise UserApiError(HTTPStatus.FORBIDDEN, "admin_required")
        return identity, profile

    def _initialize(self) -> None:
        if self._database is not None:
            return
        with self._initialize_lock:
            if self._database is not None:
                return
            import firebase_admin
            from firebase_admin import auth, firestore

            try:
                app = firebase_admin.get_app()
            except ValueError:
                app = firebase_admin.initialize_app(options={"projectId": self.project_id})
            self._auth = auth
            self._firestore = firestore
            self._database = firestore.client(app=app)

    def _users(self) -> Any:
        self._initialize()
        return self._database.collection(self.collection_name)

    def _invitations(self) -> Any:
        self._initialize()
        return self._database.collection(self.invitation_collection_name)

    def _invitation_reference(self, email: str) -> Any:
        normalized_email = self._validate_email(email)
        document_id = hashlib.sha256(normalized_email.encode("utf-8")).hexdigest()
        return self._invitations().document(document_id)

    def _sync_claims(self, uid: str, profile: dict[str, Any]) -> None:
        self._initialize()
        self._auth.set_custom_user_claims(
            uid,
            {
                "admin": profile.get("role") == "ADMIN",
                "approved": profile.get("status") == "ACTIVE",
            },
        )

    def _favorite_reference(self, uid: str, key: str) -> Any:
        document_id = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self._users().document(uid).collection("favorites").document(document_id)

    @staticmethod
    def _validate_favorite_key(value: str) -> str:
        key = str(value or "").strip()
        if not key or len(key) > 300:
            raise UserApiError(HTTPStatus.BAD_REQUEST, "invalid_favorite_key")
        return key

    @staticmethod
    def _validate_email(value: str) -> str:
        email = str(value or "").strip().casefold()
        if (
            not email
            or len(email) > 254
            or email.count("@") != 1
            or any(character.isspace() for character in email)
        ):
            raise UserApiError(HTTPStatus.BAD_REQUEST, "invalid_email")
        local, domain = email.split("@", 1)
        if not local or not domain or "." not in domain:
            raise UserApiError(HTTPStatus.BAD_REQUEST, "invalid_email")
        return email

    @staticmethod
    def _favorite_metadata(value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise UserApiError(HTTPStatus.BAD_REQUEST, "invalid_metadata")
        allowed = {
            "module", "itemId", "quality", "name", "currencyItemId",
            "currencyName", "sourceWorldId", "sourceWorldName", "targetValue",
            "targetPrice", "buyTarget", "sellTarget", "maxCapital", "notes",
            "preferredWorldName", "alertsEnabled", "iconId",
        }
        result = {key: value[key] for key in allowed if key in value}
        for key in ("itemId", "currencyItemId", "sourceWorldId", "iconId"):
            if key in result and result[key] is not None:
                number = int(result[key])
                if number <= 0:
                    raise UserApiError(HTTPStatus.BAD_REQUEST, "invalid_metadata")
                result[key] = number
        for key in ("targetValue", "targetPrice", "buyTarget", "sellTarget", "maxCapital"):
            if key in result and result[key] not in (None, ""):
                number = float(result[key])
                if number < 0 or number != number or number == float("inf"):
                    raise UserApiError(HTTPStatus.BAD_REQUEST, "invalid_metadata")
                result[key] = number
            elif key in result:
                result[key] = None
        for key, maximum in (("notes", 800), ("preferredWorldName", 80), ("sourceWorldName", 80)):
            if key in result:
                result[key] = str(result[key] or "").strip()[:maximum]
        if "alertsEnabled" in result:
            result["alertsEnabled"] = bool(result["alertsEnabled"])
        if len(str(result)) > 4000:
            raise UserApiError(HTTPStatus.BAD_REQUEST, "metadata_too_large")
        return result

    @classmethod
    def _public_profile(cls, profile: dict[str, Any]) -> dict[str, Any]:
        return cls._serialize(
            {
                key: profile.get(key)
                for key in (
                    "uid", "email", "displayName", "photoURL", "status", "role",
                    "createdAt", "lastLoginAt", "updatedAt",
                )
            }
        )

    @classmethod
    def _public_invitation(cls, invitation_id: str, invitation: dict[str, Any]) -> dict[str, Any]:
        return cls._serialize(
            {
                "id": invitation_id,
                "email": invitation.get("email"),
                "createdAt": invitation.get("createdAt"),
                "updatedAt": invitation.get("updatedAt"),
            }
        )

    @classmethod
    def _serialize(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat()
        if isinstance(value, dict):
            return {key: cls._serialize(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._serialize(item) for item in value]
        return value


def _favorite_observation_context(
    *,
    dashboard: dict[str, Any],
    market_items: dict[str, Any],
    opportunities: dict[str, Any],
    signals: dict[str, Any],
) -> dict[str, dict[Any, dict[str, Any]]]:
    market = {
        (int(item["itemId"]), str(item.get("quality") or "NQ")): item
        for item in market_items.get("items", [])
        if item.get("itemId")
    }
    routes: dict[str, dict[str, Any]] = {}
    for item in opportunities.get("opportunities", []):
        suffix = f'{item.get("itemId")}:{item.get("quality") or "NQ"}:{item.get("sourceWorldId")}'
        routes[f"opportunity:{suffix}"] = item
        routes[f"snipe:{suffix}"] = item
    conversions = {
        "conversion:" + ":".join(
            str(value)
            for value in (
                item.get("currencyItemId"), item.get("currencyQuantity"),
                item.get("rewardItemId"), item.get("rewardQuantity"),
                1 if item.get("rewardIsHq") else 0,
            )
        ): item
        for item in dashboard.get("conversions", [])
    }
    signal_map = {
        str(item["key"]): item
        for item in signals.get("signals", [])
        if item.get("key")
    }
    return {"market": market, "routes": routes, "conversions": conversions, "signals": signal_map}


def _favorite_observation(
    favorite: dict[str, Any],
    *,
    context: dict[str, dict[Any, dict[str, Any]]],
    market_snapshot_id: str,
    observed_at: str,
) -> dict[str, Any] | None:
    key = str(favorite.get("key") or "")
    item_id = favorite.get("itemId")
    quality = str(favorite.get("quality") or "NQ")
    try:
        market = context["market"].get((int(item_id), quality)) if item_id else None
    except (TypeError, ValueError):
        market = None
    route = context["routes"].get(key)
    conversion = context["conversions"].get(key)
    signal = context["signals"].get(key)
    buy_price = _finite_number(
        (route or {}).get("averagePurchasePrice")
        or (route or {}).get("sourcePrice")
        or (market or {}).get("minListingPrice")
        or (conversion or {}).get("marketUnitPrice")
    )
    sell_price = _finite_number(
        (route or {}).get("conservativeSellPrice")
        or (market or {}).get("averageSalePrice")
        or (conversion or {}).get("marketUnitPrice")
    )
    velocity = _finite_number(
        (route or {}).get("dailySaleVelocity")
        or (market or {}).get("dailySaleVelocity")
        or (conversion or {}).get("dailySaleVelocity")
        or (signal or {}).get("context", {}).get("velocity")
    )
    state = (
        (signal or {}).get("state")
        or (market or {}).get("trend", {}).get("signal")
        or (route or {}).get("confidenceBand")
    )
    if buy_price is None and sell_price is None and velocity is None and not state:
        return None
    return {
        "marketSnapshotId": market_snapshot_id,
        "observedAt": observed_at,
        "itemId": int(item_id) if item_id else None,
        "quality": quality,
        "currentBuyPrice": buy_price,
        "currentSellPrice": sell_price,
        "dailySaleVelocity": velocity,
        "state": state,
        "sourceWorldName": (route or {}).get("sourceWorldName"),
        "metricValue": _finite_number((signal or {}).get("metricValue")),
    }


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None
