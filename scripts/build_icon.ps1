param(
    [string]$SourcePng = "assets/icons/icon.png",
    [string]$OutputIco = "assets/icons/icon.ico",
    [string]$TrayPng = "assets/icons/tray-icon.png",
    [string]$TrayIco = "assets/icons/tray-icon.ico",
    [string]$ExtensionIconsDir = "browser_capture/ai_capture_extension/icons",
    [string]$WebIconsDir = "app/static/icons"
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase
Add-Type -AssemblyName System.Drawing

$projectRoot = Split-Path -Parent $PSScriptRoot
$sourcePath = Join-Path $projectRoot $SourcePng
$outputPath = Join-Path $projectRoot $OutputIco
$trayPngPath = Join-Path $projectRoot $TrayPng
$trayIcoPath = Join-Path $projectRoot $TrayIco
$extensionIconsPath = Join-Path $projectRoot $ExtensionIconsDir
$webIconsPath = Join-Path $projectRoot $WebIconsDir

if (-not (Test-Path $sourcePath)) {
    throw "Source PNG not found: $sourcePath"
}

$outputDir = Split-Path -Parent $outputPath
if ($outputDir -and -not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
}

function Get-PngBytesForSize {
    param(
        [string]$Path,
        [int]$Size
    )

    $bitmap = New-Object System.Windows.Media.Imaging.BitmapImage
    $bitmap.BeginInit()
    $bitmap.CacheOption = [System.Windows.Media.Imaging.BitmapCacheOption]::OnLoad
    $bitmap.UriSource = [Uri]::new($Path)
    $bitmap.DecodePixelWidth = $Size
    $bitmap.DecodePixelHeight = $Size
    $bitmap.EndInit()
    $bitmap.Freeze()

    $frame = [System.Windows.Media.Imaging.BitmapFrame]::Create($bitmap)
    $encoder = New-Object System.Windows.Media.Imaging.PngBitmapEncoder
    $encoder.Frames.Add($frame)

    $stream = New-Object System.IO.MemoryStream
    $encoder.Save($stream)
    return [byte[]]$stream.ToArray()
}

function Write-PngForSize {
    param(
        [string]$Path,
        [int]$Size,
        [string]$Destination
    )

    $bitmap = New-Object System.Windows.Media.Imaging.BitmapImage
    $bitmap.BeginInit()
    $bitmap.CacheOption = [System.Windows.Media.Imaging.BitmapCacheOption]::OnLoad
    $bitmap.UriSource = [Uri]::new($Path)
    $bitmap.DecodePixelWidth = $Size
    $bitmap.DecodePixelHeight = $Size
    $bitmap.EndInit()
    $bitmap.Freeze()

    $frame = [System.Windows.Media.Imaging.BitmapFrame]::Create($bitmap)
    $encoder = New-Object System.Windows.Media.Imaging.PngBitmapEncoder
    $encoder.Frames.Add($frame)

    $stream = [System.IO.File]::Open($Destination, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write)
    try {
        $encoder.Save($stream)
    } finally {
        $stream.Close()
    }
}

function Add-Bytes {
    param(
        [System.Collections.Generic.List[byte]]$Target,
        [byte[]]$Bytes
    )
    foreach ($byteValue in $Bytes) {
        $Target.Add($byteValue) | Out-Null
    }
}

function Write-IcoFromPngSource {
    param(
        [string]$Path,
        [string]$Destination,
        [int[]]$Sizes
    )

    $entries = @()
    foreach ($size in $Sizes) {
        $pngBytes = Get-PngBytesForSize -Path $Path -Size $size
        $entries += [PSCustomObject]@{
            Size = $size
            Bytes = [byte[]]$pngBytes
            Length = $pngBytes.Length
        }
    }

    $headerSize = 6 + (16 * $entries.Count)
    $offset = $headerSize
    $bytes = [System.Collections.Generic.List[byte]]::new()

    Add-Bytes $bytes ([System.BitConverter]::GetBytes([UInt16]0))
    Add-Bytes $bytes ([System.BitConverter]::GetBytes([UInt16]1))
    Add-Bytes $bytes ([System.BitConverter]::GetBytes([UInt16]$entries.Count))

    foreach ($entry in $entries) {
        $sizeByte = if ($entry.Size -ge 256) { [byte]0 } else { [byte]$entry.Size }
        $bytes.Add($sizeByte) | Out-Null
        $bytes.Add($sizeByte) | Out-Null
        $bytes.Add([byte]0) | Out-Null
        $bytes.Add([byte]0) | Out-Null
        Add-Bytes $bytes ([System.BitConverter]::GetBytes([UInt16]1))
        Add-Bytes $bytes ([System.BitConverter]::GetBytes([UInt16]32))
        Add-Bytes $bytes ([System.BitConverter]::GetBytes([UInt32]$entry.Length))
        Add-Bytes $bytes ([System.BitConverter]::GetBytes([UInt32]$offset))
        $offset += $entry.Length
    }

    foreach ($entry in $entries) {
        Add-Bytes $bytes $entry.Bytes
    }

    [System.IO.File]::WriteAllBytes($Destination, $bytes.ToArray())
}

function New-RoundedRectPath {
    param(
        [float]$X,
        [float]$Y,
        [float]$Width,
        [float]$Height,
        [float]$Radius
    )

    $diameter = $Radius * 2
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $path.AddArc($X, $Y, $diameter, $diameter, 180, 90)
    $path.AddArc($X + $Width - $diameter, $Y, $diameter, $diameter, 270, 90)
    $path.AddArc($X + $Width - $diameter, $Y + $Height - $diameter, $diameter, $diameter, 0, 90)
    $path.AddArc($X, $Y + $Height - $diameter, $diameter, $diameter, 90, 90)
    $path.CloseFigure()
    return $path
}

function New-TrayIconPng {
    param(
        [string]$Destination
    )

    $size = 256
    $bitmap = New-Object System.Drawing.Bitmap $size, $size
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
        $graphics.Clear([System.Drawing.Color]::Transparent)

        $outerRect = New-Object System.Drawing.RectangleF 12, 12, 232, 232
        $path = New-RoundedRectPath -X $outerRect.X -Y $outerRect.Y -Width $outerRect.Width -Height $outerRect.Height -Radius 56
        try {
            $bgBrush = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
                ([System.Drawing.PointF]::new(0, 0)),
                ([System.Drawing.PointF]::new($size, $size)),
                ([System.Drawing.Color]::FromArgb(255, 10, 57, 93)),
                ([System.Drawing.Color]::FromArgb(255, 22, 98, 146))
            )
            try {
                $graphics.FillPath($bgBrush, $path)
            } finally {
                $bgBrush.Dispose()
            }

            $borderPen = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(180, 140, 220, 255)), 6
            try {
                $graphics.DrawPath($borderPen, $path)
            } finally {
                $borderPen.Dispose()
            }
        } finally {
            $path.Dispose()
        }

        $shadowBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(70, 0, 0, 0))
        $textBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 255, 255, 255))
        $font = New-Object System.Drawing.Font("Segoe UI", 150, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
        $format = New-Object System.Drawing.StringFormat
        $format.Alignment = [System.Drawing.StringAlignment]::Center
        $format.LineAlignment = [System.Drawing.StringAlignment]::Center
        try {
            $shadowRect = New-Object System.Drawing.RectangleF 18, 18, 232, 232
            $textRect = New-Object System.Drawing.RectangleF 12, 6, 232, 232
            $graphics.DrawString("S", $font, $shadowBrush, $shadowRect, $format)
            $graphics.DrawString("S", $font, $textBrush, $textRect, $format)
        } finally {
            $format.Dispose()
            $font.Dispose()
            $textBrush.Dispose()
            $shadowBrush.Dispose()
        }

        $bitmap.Save($Destination, [System.Drawing.Imaging.ImageFormat]::Png)
    } finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

Write-IcoFromPngSource -Path $sourcePath -Destination $outputPath -Sizes @(16, 24, 32, 48, 64, 128, 256)
New-TrayIconPng -Destination $trayPngPath
Write-IcoFromPngSource -Path $trayPngPath -Destination $trayIcoPath -Sizes @(16, 20, 24, 32, 40, 48, 64)

Write-Host "Generated icon:" $outputPath
Write-Host "Generated tray icon:" $trayPngPath
Write-Host "Generated tray icon:" $trayIcoPath

if (-not (Test-Path $extensionIconsPath)) {
    New-Item -ItemType Directory -Path $extensionIconsPath | Out-Null
}

foreach ($size in @(16, 32, 48, 128)) {
    $destination = Join-Path $extensionIconsPath "$size.png"
    Write-PngForSize -Path $sourcePath -Size $size -Destination $destination
    Write-Host "Generated extension icon:" $destination
}

if (-not (Test-Path $webIconsPath)) {
    New-Item -ItemType Directory -Path $webIconsPath | Out-Null
}

$faviconIcoPath = Join-Path $webIconsPath "favicon.ico"
[System.IO.File]::Copy($outputPath, $faviconIcoPath, $true)
Write-Host "Generated web icon:" $faviconIcoPath

foreach ($size in @(16, 32, 180)) {
    $fileName = switch ($size) {
        16 { "favicon-16.png" }
        32 { "favicon-32.png" }
        180 { "apple-touch-icon.png" }
    }
    $destination = Join-Path $webIconsPath $fileName
    Write-PngForSize -Path $sourcePath -Size $size -Destination $destination
    Write-Host "Generated web icon:" $destination
}
