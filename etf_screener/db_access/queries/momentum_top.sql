-- Top 50 funds for BOTH 1-week and 1-month return (was the Top 50 momentum tab)
-- rows_needed = how far down both the 1W and the 1M list you must go to reach the fund
WITH positions AS (
    SELECT *,
           rank() OVER (ORDER BY "Return Rank (1W)" ASC) AS pos_1w,
           rank() OVER (ORDER BY "Return Rank (1M)" ASC) AS pos_1m
    FROM report
    WHERE "Return Rank (1W)" IS NOT NULL AND "Return Rank (1M)" IS NOT NULL
)
SELECT greatest(pos_1w, pos_1m) AS rows_needed, pos_1w, pos_1m,
       Ticker, Name, "Morningstar Category", "Total Return (1W)", "Total Return (1M)",
       round("Profile ST Score", 1) AS st_score, round("Profile LT Score", 1) AS lt_score
FROM positions
QUALIFY rank() OVER (ORDER BY greatest(pos_1w, pos_1m)) <= 50
ORDER BY (pos_1w + pos_1m) / 2, pos_1w;
