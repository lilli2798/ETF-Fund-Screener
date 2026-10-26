-- Score and rank of {ticker} in every saved report
SELECT run_time::DATE AS run_date, 'LT' AS profile, round("Profile LT Score", 1) AS score,
       "Profile LT Rank In Category" AS rank_in_category, "Profile LT Rank Overall" AS rank_overall,
       "Profile LT Selected Flag"::INTEGER AS selected, source_file
FROM reports WHERE upper(Ticker) = upper('{ticker}')
UNION ALL
SELECT run_time::DATE, 'ST', round("Profile ST Score", 1), "Profile ST Rank In Category",
       "Profile ST Rank Overall", "Profile ST Selected Flag"::INTEGER, source_file
FROM reports WHERE upper(Ticker) = upper('{ticker}')
ORDER BY run_date, profile;
