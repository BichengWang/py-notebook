-- Synthetic exposure and conversion events for three experiments. No real users, no real traffic.
-- Deterministic: every random draw is an md5 hash of (experiment, user, salt), so reruns give identical rows.
CREATE TABLE experiment_viewed (user_id text, "timestamp" timestamp, experiment_id text, variation_id int);
CREATE TABLE orders (user_id text, "timestamp" timestamp, order_id text, amount numeric);
CREATE TABLE refunds (user_id text, "timestamp" timestamp);
CREATE TABLE page_loads (user_id text, "timestamp" timestamp, load_ms numeric);

CREATE FUNCTION u01(seed text) RETURNS float8 LANGUAGE sql IMMUTABLE AS
$$ SELECT (('x' || substr(md5(seed), 1, 8))::bit(32)::bigint)::float8 / 4294967296.0 + 1e-12 $$;
CREATE FUNCTION norm(seed text) RETURNS float8 LANGUAGE sql IMMUTABLE AS
$$ SELECT sqrt(-2 * ln(u01(seed || 'a'))) * cos(2 * pi() * u01(seed || 'b')) $$;

-- exp, users per arm, purchase p (control, treatment), refund p (c, t), load ms mean (c, t) and sd, order amount mean (c, t)
CREATE TABLE plan (exp text, n int, p_buy_c float8, p_buy_t float8, p_ref_c float8, p_ref_t float8,
                   load_c float8, load_t float8, load_sd float8, amt_c float8, amt_t float8, salt text);
INSERT INTO plan VALUES
  ('ranker-v2', 20000, 0.100, 0.120, 0.020, 0.020, 410, 410.5,  90, 30.0, 30.5, 's2'),
  ('ranker-v3', 20000, 0.100, 0.113, 0.020, 0.020, 410, 411.3, 120, 30.0, 30.0, 's3'),
  ('ranker-v4', 20000, 0.100, 0.1039, 0.020, 0.020, 410, 410.0,  90, 30.0, 30.0, 's4');

CREATE TABLE assignments AS
SELECT p.exp, p.salt, g AS i, (g % 2) AS arm,
       p.exp || '_u' || lpad(g::text, 6, '0') AS user_id,
       timestamp '2026-09-01 00:00:00' + (u01(p.exp || g || 't') * 14 * 24 * 3600) * interval '1 second' AS ts
FROM plan p, generate_series(0, 2 * p.n - 1) AS g;

INSERT INTO experiment_viewed SELECT user_id, ts, exp, arm FROM assignments;

-- Purchases: 1 order, plus a second one 30% of the time and a third 10% of the time.
INSERT INTO orders
SELECT a.user_id, a.ts + (1 + 40 * u01(a.user_id || 'o' || k)) * interval '1 hour', a.user_id || '_o' || k,
       round((greatest(5, (CASE a.arm WHEN 0 THEN p.amt_c ELSE p.amt_t END) + 12 * norm(a.user_id || 'amt' || k)))::numeric, 2)
FROM assignments a JOIN plan p ON p.exp = a.exp
CROSS JOIN generate_series(1, 3) k
WHERE u01(a.user_id || 'buy' || p.salt) < (CASE a.arm WHEN 0 THEN p.p_buy_c ELSE p.p_buy_t END)
  AND (k = 1 OR (k = 2 AND u01(a.user_id || 'k2') < 0.3) OR (k = 3 AND u01(a.user_id || 'k2') < 0.3 AND u01(a.user_id || 'k3') < 0.33));

INSERT INTO refunds
SELECT a.user_id, a.ts + (30 + 30 * u01(a.user_id || 'rt')) * interval '1 hour'
FROM assignments a JOIN plan p ON p.exp = a.exp
WHERE u01(a.user_id || 'ref' || p.salt) < (CASE a.arm WHEN 0 THEN p.p_ref_c ELSE p.p_ref_t END);

INSERT INTO page_loads
SELECT a.user_id, a.ts + interval '1 minute',
       round((greatest(50, (CASE a.arm WHEN 0 THEN p.load_c ELSE p.load_t END) + p.load_sd * norm(a.user_id || 'load')))::numeric, 1)
FROM assignments a JOIN plan p ON p.exp = a.exp;

CREATE INDEX ON experiment_viewed (experiment_id);
CREATE INDEX ON orders (user_id);
CREATE INDEX ON refunds (user_id);
CREATE INDEX ON page_loads (user_id);
