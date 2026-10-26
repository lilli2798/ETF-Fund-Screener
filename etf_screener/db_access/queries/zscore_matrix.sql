-- 1Y vs 3Y Z-score: Core (both >= +1), Momentum (1Y >= +1, 3Y < 0), Value dip (1Y < 0, 3Y >= +1)
-- Z-scores compare each fund's Yahoo Sharpe with funds of the same Yahoo Subsector.
--   Core      long-term compounders still leading: candidates to hold
--   Momentum  recent surge without a long record: tactical trades, not anchors
--   Value     strong 3-year record in a temporary slump: possible buy-the-dip
SELECT CASE WHEN "Z Score 1y" >= 1 AND "Z Score 3y" >= 1 THEN 'Core'
            WHEN "Z Score 1y" >= 1 THEN 'Momentum'
            ELSE 'Value' END AS zscore_group,
       Ticker, Name, "Yahoo Subsector", "Morningstar Category",
       round("Z Score 1y", 2) AS z_1y, round("Z Score 3y", 2) AS z_3y,
       round("Profile LT Score", 1) AS lt_score, round("Profile ST Score", 1) AS st_score
FROM report
WHERE ("Z Score 1y" >= 1 AND "Z Score 3y" >= 1)
   OR ("Z Score 1y" >= 1 AND "Z Score 3y" < 0)
   OR ("Z Score 1y" < 0 AND "Z Score 3y" >= 1)
ORDER BY CASE zscore_group WHEN 'Core' THEN 1 WHEN 'Momentum' THEN 2 ELSE 3 END,
         "Z Score 1y" + "Z Score 3y" DESC;
