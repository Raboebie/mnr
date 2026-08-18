<?php
$logFile = 'stats.txt';

// Initialize file with zeros if it doesn't exist
if (!file_exists($logFile)) {
    file_put_contents($logFile, "Visits: 0\nDiscord Clicks: 0");
}

$action = $_GET['action'] ?? '';

if ($action === 'visit' || $action === 'click') {
    $content = file_get_contents($logFile);
    
    // Parse the counts
    preg_match('/Visits: (\d+)/', $content, $vMatch);
    preg_match('/Discord Clicks: (\d+)/', $content, $cMatch);
    
    $visits = (int)$vMatch[1];
    $clicks = (int)$cMatch[1];

    if ($action === 'visit') $visits++;
    if ($action === 'click') $clicks++;

    // Save back to file
    $newData = "Visits: $visits\nDiscord Clicks: $clicks";
    file_put_contents($logFile, $newData);
    
    echo "Success";
}
?>