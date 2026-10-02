$python = "C:\Users\saith\AppData\Local\Programs\Python\Python313\python.exe"
$backendDir = "D:\Job Scraper\rtl-dv-job-radar\backend"
$logFile = "D:\Job Scraper\rtl-dv-job-radar\backend_server.log"

Set-Location $backendDir
$env:PYTHONPATH = $backendDir

Start-Transcript -Path $logFile -Append
& $python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Stop-Transcript
