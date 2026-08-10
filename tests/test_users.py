from http import HTTPStatus
import unittest

from gil_intelligence.cloud.users import FirebaseUserService, UserApiError


class FakeSnapshot:
    def __init__(self, reference, data):
        self.reference = reference
        self.id = reference.path[-1]
        self.exists = data is not None
        self._data = data

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class FakeDocument:
    def __init__(self, store, path):
        self.store = store
        self.path = path

    def get(self):
        return FakeSnapshot(self, self.store.get(self.path))

    def set(self, value, merge=False):
        if merge:
            value = {**self.store.get(self.path, {}), **value}
        self.store[self.path] = dict(value)

    def delete(self):
        self.store.pop(self.path, None)

    def collection(self, name):
        return FakeCollection(self.store, (*self.path, name))


class FakeCollection:
    def __init__(self, store=None, path=("users",)):
        self.store = store if store is not None else {}
        self.path = path

    def document(self, document_id):
        return FakeDocument(self.store, (*self.path, document_id))

    def stream(self):
        depth = len(self.path) + 1
        return [
            FakeSnapshot(FakeDocument(self.store, path), data)
            for path, data in self.store.items()
            if len(path) == depth and path[:-1] == self.path
        ]


class FakeAuth:
    def __init__(self):
        self.claims = {}
        self.disabled = {}

    def set_custom_user_claims(self, uid, claims):
        self.claims[uid] = claims

    def update_user(self, uid, *, disabled):
        self.disabled[uid] = disabled


class InMemoryUserService(FirebaseUserService):
    def __init__(self, identities):
        super().__init__(project_id="test", bootstrap_admin_email="owner@example.com")
        self.identities = identities
        self.collection = FakeCollection()
        self._auth = FakeAuth()
        self._database = object()

    def _identity(self, authorization):
        token = str(authorization or "").removeprefix("Bearer ")
        if token not in self.identities:
            raise UserApiError(HTTPStatus.UNAUTHORIZED, "invalid_token")
        return self.identities[token]

    def _users(self):
        return self.collection


def google_identity(uid, email):
    return {
        "uid": uid,
        "email": email,
        "email_verified": True,
        "name": email.split("@", 1)[0].title(),
        "firebase": {"sign_in_provider": "google.com"},
    }


class FirebaseUserServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = InMemoryUserService(
            {
                "owner": google_identity("uid-owner", "owner@example.com"),
                "member": google_identity("uid-member", "member@example.com"),
            }
        )

    def test_bootstrap_admin_is_active_and_new_user_starts_pending(self):
        owner = self.service.register("Bearer owner")
        member = self.service.register("Bearer member")

        self.assertEqual((owner["status"], owner["role"]), ("ACTIVE", "ADMIN"))
        self.assertEqual((member["status"], member["role"]), ("PENDING", "USER"))
        self.assertEqual(self.service._auth.claims["uid-owner"], {"admin": True, "approved": True})
        self.assertEqual(self.service._auth.claims["uid-member"], {"admin": False, "approved": False})

    def test_pending_user_cannot_write_favorites_until_admin_approves(self):
        self.service.register("Bearer owner")
        self.service.register("Bearer member")
        with self.assertRaisesRegex(UserApiError, "account_pending"):
            self.service.put_favorite("Bearer member", "market:123:NQ", {"name": "Item"})

        self.service.update_user("Bearer owner", "uid-member", {"status": "ACTIVE"})
        saved = self.service.put_favorite(
            "Bearer member", "market:123:NQ", {"name": "Item", "unsafe": "discarded"}
        )

        self.assertEqual(saved["key"], "market:123:NQ")
        self.assertEqual(saved["name"], "Item")
        self.assertNotIn("unsafe", saved)
        self.assertEqual(len(self.service.favorites("Bearer member")), 1)

        self.service.delete_favorite("Bearer member", "market:123:NQ")
        self.assertEqual(self.service.favorites("Bearer member"), [])

    def test_market_access_requires_an_active_account(self):
        self.service.register("Bearer owner")
        self.service.register("Bearer member")

        self.assertEqual(self.service.authorize("Bearer owner")["role"], "ADMIN")
        with self.assertRaisesRegex(UserApiError, "account_pending"):
            self.service.authorize("Bearer member")

    def test_normal_user_cannot_list_users_and_admin_cannot_demote_self(self):
        self.service.register("Bearer owner")
        self.service.register("Bearer member")
        self.service.update_user("Bearer owner", "uid-member", {"status": "ACTIVE"})

        with self.assertRaisesRegex(UserApiError, "admin_required"):
            self.service.list_users("Bearer member")
        with self.assertRaises(UserApiError) as context:
            self.service.update_user("Bearer owner", "uid-owner", {"role": "USER"})
        self.assertEqual(context.exception.code, "cannot_lock_current_admin")

    def test_suspension_disables_firebase_account(self):
        self.service.register("Bearer owner")
        self.service.register("Bearer member")
        self.service.update_user("Bearer owner", "uid-member", {"status": "SUSPENDED"})

        self.assertTrue(self.service._auth.disabled["uid-member"])
        with self.assertRaisesRegex(UserApiError, "account_suspended"):
            self.service.me("Bearer member")


if __name__ == "__main__":
    unittest.main()
