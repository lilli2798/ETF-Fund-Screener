-- Weakest 3 funds per category on BOTH profiles (bottom of the LT and ST ranks), categories with 10+ funds
WITH ranked AS (
    SELECT *,
           count(*) OVER (PARTITION BY "Morningstar Category") AS funds_in_category,
           max("Profile LT Rank In Category") OVER (PARTITION BY "Morningstar Category") AS worst_lt_rank,
           max("Profile ST Rank In Category") OVER (PARTITION BY "Morningstar Category") AS worst_st_rank
    FROM report
    WHERE "Profile LT Score" IS NOT NULL AND "Profile ST Score" IS NOT NULL
)
SELECT Ticker, Name, "Morningstar Category", funds_in_category,
       "Profile LT Rank In Category" AS lt_rank, round("Profile LT Score", 1) AS lt_score,
       "Profile ST Rank In Category" AS st_rank, round("Profile ST Score", 1) AS st_score,
       "Total Return (1Y)", "Total Return (3M)"
FROM ranked
WHERE funds_in_category >= 10
  AND "Profile LT Rank In Category" > worst_lt_rank - 3
  AND "Profile ST Rank In Category" > worst_st_rank - 3
ORDER BY "Morningstar Category", lt_rank DESC;
