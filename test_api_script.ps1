try {
    $channels = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/channels" -Method Get
    $targetId = "batron-creek-mall-test"
    $found = $channels | Where-Object { $_.id -eq $targetId }
    if (-not $found) {
        Write-Output "Error: Channel $targetId not found."
        return
    }
    Write-Output "Found channel: $targetId"

    $tuneBody = @{ channel_id = $targetId } | ConvertTo-Json
    $tuneResponse = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/scanner/tune" -Method Post -Body $tuneBody -ContentType "application/json"
    Write-Output "Tune request successful."

    $status = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/scanner/status" -Method Get
    Write-Output "State: $($status.state)"
    Write-Output "Active Channel ID: $($status.active_channel.id)"
    Write-Output "Active Channel Name: $($status.active_channel.name)"
    Write-Output "Active Channel Frequency: $($status.active_channel.frequency_hz)"
} catch {
    Write-Output "API is unreachable or returned an error: $($_.Exception.Message)"
}
