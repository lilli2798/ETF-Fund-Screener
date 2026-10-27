-- Funds in the top {top=5} of their category for BOTH the long-term and short-term profiles
SELECT Ticker, Name, "Morningstar Category",
       round("Profile LT Score", 1) AS lt_score, "Profile LT Rank In Category" AS lt_rank,
       round("Profile ST Score", 1) AS st_score, "Profile ST Rank In Category" AS st_rank,
       "Total Return (1Y)", "Adjusted Expense Ratio"
FROM report
WHERE "Profile LT Rank In Category" <= {top=5} AND "Profile ST Rank In Category" <= {top=5}
ORDER BY "Morningstar Category", lt_rank;
