$rssFirst = @(
  "ТАСС",
  "РБК",
  "iXBT.com",
  "АиФ news",
  "АиФ articles"
)

$htmlFirst = @(
  "РИА Новости",
  "Ведомости news",
  "Ведомости articles",
  "Коммерсантъ news",
  "Коммерсантъ corp",
  "Коммерсантъ main",
  "Lenta.ru",
  "МК",
  "Life.ru",
  "CNews",
  "BFM.ru",
  "Хабр",
  "RT на русском"
)

foreach ($source in $rssFirst) {
  Write-Host "`n=== DISCOVERY: $source ===" -ForegroundColor Cyan
  python -m jarvis.ingestion.cli.run_source --source $source
}

foreach ($source in $htmlFirst) {
  Write-Host "`n=== DISCOVERY: $source ===" -ForegroundColor Yellow
  python -m jarvis.ingestion.cli.run_source --source $source

  Write-Host "=== ENRICH TOP-5: $source ===" -ForegroundColor Green
  python -m jarvis.ingestion.cli.enrich_source --source $source --limit 5
}
