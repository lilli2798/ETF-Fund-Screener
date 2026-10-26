-- Funds that beat the best index far more often than they trailed the worst (Yearly Beat-Trail Diff >= {min_diff=20}), with their yearly bands
-- Options: min_diff=20 (percent), min_years=5 (short histories inflate the diff: 1 year beaten = 100%)
-- swing_years = years in the top 10% + years in the bottom 10% of all funds; high = big swings, low = steady
-- t10..t90 = years in each 10% band (t10 = best tenth, t20 = 80th-90th percentile, ...), b10 = worst tenth
SELECT Ticker, Name, "Morningstar Category",
       "Yearly Periods With Data"::INTEGER AS years,
       round("Yearly Beat-Trail Diff", 1) AS yearly_diff,
       round("Volatile Beat-Trail Diff", 1) AS volatile_diff,
       "Yearly Beat All Indexes"::INTEGER AS beat_all, "Yearly Trailed All Indexes"::INTEGER AS trailed_all,
       ("Yearly Top 10% Count" + "Yearly Bottom 10% Count")::INTEGER AS swing_years,
       "Yearly Top 10% Count"::INTEGER AS t10, "Yearly Top 20% Count"::INTEGER AS t20, "Yearly Top 30% Count"::INTEGER AS t30,
       "Yearly Top 40% Count"::INTEGER AS t40, "Yearly Top 50% Count"::INTEGER AS t50, "Yearly Top 60% Count"::INTEGER AS t60,
       "Yearly Top 70% Count"::INTEGER AS t70, "Yearly Top 80% Count"::INTEGER AS t80, "Yearly Top 90% Count"::INTEGER AS t90,
       "Yearly Bottom 10% Count"::INTEGER AS b10,
       round("Profile LT Score", 1) AS lt_score, round("Profile ST Score", 1) AS st_score
FROM report
WHERE "Yearly Beat-Trail Diff" >= {min_diff=20}
  AND "Yearly Periods With Data" >= {min_years=5}
ORDER BY yearly_diff DESC, swing_years, years DESC;
