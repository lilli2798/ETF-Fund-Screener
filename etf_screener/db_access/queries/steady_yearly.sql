-- Funds with a positive return in each of the last 5 calendar years, with their LT score
WITH last5 AS (
    SELECT ticker, count(*) AS years, min(total_return) AS worst_year, avg(total_return) AS avg_year
    FROM yearly_returns
    WHERE year > (SELECT max(year) FROM yearly_returns) - 5
    GROUP BY ticker
    HAVING count(*) = 5 AND min(total_return) > 0
)
SELECT r.Ticker, r.Name, r."Morningstar Category",
       round(l.worst_year * 100, 1) AS worst_year_pct, round(l.avg_year * 100, 1) AS avg_year_pct,
       round(r."Profile LT Score", 1) AS lt_score, r."Profile LT Rank In Category" AS lt_rank
FROM last5 l JOIN report r ON r.Ticker = l.ticker
ORDER BY lt_score DESC NULLS LAST;
