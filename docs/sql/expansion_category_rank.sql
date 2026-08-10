-- BigQuery parameters:
--   @scope STRING       e.g. "Cactuar"
--   @launch_at TIMESTAMP
-- Compares the 28 complete days before launch with the first 14 launch days.
WITH latest_catalog AS (
  SELECT item_id, search_category_id, search_category_name,
         ui_category_id, ui_category_name
  FROM `cactuar-gil-intelligence-8148.cactuar_gil.item_catalog`
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY item_id ORDER BY extracted_at DESC, static_snapshot_id DESC
  ) = 1
),
snapshot_item_velocity AS (
  SELECT
    aggregate.collected_at,
    aggregate.item_id,
    SUM(COALESCE(aggregate.daily_sale_velocity, 0)) AS daily_velocity
  FROM `cactuar-gil-intelligence-8148.cactuar_gil.market_aggregates` AS aggregate
  WHERE LOWER(aggregate.scope) = LOWER(@scope)
    AND aggregate.scope_level = 'WORLD'
    AND aggregate.collected_at >= TIMESTAMP_SUB(@launch_at, INTERVAL 28 DAY)
    AND aggregate.collected_at < TIMESTAMP_ADD(@launch_at, INTERVAL 14 DAY)
  GROUP BY aggregate.collected_at, aggregate.item_id
),
daily_item_velocity AS (
  SELECT
    DATE(collected_at) AS observed_date,
    item_id,
    AVG(daily_velocity) AS daily_velocity
  FROM snapshot_item_velocity
  GROUP BY observed_date, item_id
),
daily_category_velocity AS (
  SELECT
    daily.observed_date,
    COALESCE(catalog.search_category_id, catalog.ui_category_id, 0) AS category_id,
    COALESCE(
      catalog.search_category_name,
      catalog.ui_category_name,
      'Sin categoría'
    ) AS category_name,
    SUM(daily.daily_velocity) AS daily_velocity,
    COUNTIF(daily.daily_velocity > 0) AS active_items
  FROM daily_item_velocity AS daily
  LEFT JOIN latest_catalog AS catalog USING (item_id)
  GROUP BY observed_date, category_id, category_name
),
comparison AS (
  SELECT
    category_id,
    category_name,
    AVG(IF(observed_date < DATE(@launch_at), daily_velocity, NULL)) AS baseline_velocity,
    AVG(IF(observed_date >= DATE(@launch_at), daily_velocity, NULL)) AS launch_velocity,
    MAX(IF(observed_date >= DATE(@launch_at), active_items, NULL)) AS launch_active_items
  FROM daily_category_velocity
  GROUP BY category_id, category_name
)
SELECT
  category_id,
  category_name,
  ROUND(baseline_velocity, 2) AS baseline_daily_velocity,
  ROUND(launch_velocity, 2) AS launch_daily_velocity,
  ROUND(SAFE_DIVIDE(launch_velocity, baseline_velocity), 2) AS launch_multiplier,
  launch_active_items
FROM comparison
WHERE launch_velocity IS NOT NULL
ORDER BY launch_daily_velocity DESC
LIMIT 20;
