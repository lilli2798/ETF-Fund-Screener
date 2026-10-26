-- Top 15 funds by LT score in categories matching {category}, e.g. category=growth
SELECT Ticker, Name, "Morningstar Category",
       "Profile LT Rank In Category" AS lt_rank, round("Profile LT Score", 1) AS lt_score,
       "Profile ST Rank In Category" AS st_rank, round("Profile ST Score", 1) AS st_score,
       "Total Return (1Y)", "Total Return (5Y)", "Adjusted Expense Ratio"
FROM report
WHERE "Morningstar Category" ILIKE '%{category}%'
ORDER BY "Profile LT Score" DESC NULLS LAST
LIMIT 15;
