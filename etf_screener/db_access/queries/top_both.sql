-- Funds selected in their category by BOTH the long-term and short-term profiles
SELECT Ticker, Name, "Morningstar Category",
       round("Profile LT Score", 1) AS lt_score, "Profile LT Rank In Category" AS lt_rank,
       round("Profile ST Score", 1) AS st_score, "Profile ST Rank In Category" AS st_rank,
       "Total Return (1Y)", "Adjusted Expense Ratio"
FROM report
WHERE "Profile LT Selected Flag" AND "Profile ST Selected Flag"
ORDER BY "Morningstar Category", lt_rank;
