param(
    [string]$In,
    [string]$Out,
    [int]$Size = 256,
    [int]$Radius = 48,
    [int]$CropRight = 0,
    [int]$CropBottom = 0
)

# Crop watermark region, center-crop to square, apply rounded-corner alpha mask.
# Output is a transparent-background PNG with no white edges.
Add-Type -AssemblyName System.Drawing
$img = [System.Drawing.Image]::FromFile($In)

$cw = $img.Width - $CropRight
$ch = $img.Height - $CropBottom
$side = [Math]::Min($cw, $ch)
$cx = [int](($cw - $side) / 2)
$cy = [int](($ch - $side) / 2)

$bmp = New-Object System.Drawing.Bitmap($Size, $Size)
$bmp.SetResolution(96, 96)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
$g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
$g.Clear([System.Drawing.Color]::Transparent)

# rounded-rect clip path
$half = [double]$Radius
$path = New-Object System.Drawing.Drawing2D.GraphicsPath
$path.AddArc(0, 0, 2 * $half, 2 * $half, 180, 90)
$path.AddArc($Size - 2 * $half, 0, 2 * $half, 2 * $half, 270, 90)
$path.AddArc($Size - 2 * $half, $Size - 2 * $half, 2 * $half, 2 * $half, 0, 90)
$path.AddArc(0, $Size - 2 * $half, 2 * $half, 2 * $half, 90, 90)
$path.CloseFigure()
$g.SetClip($path)

$destRect = New-Object System.Drawing.Rectangle(0, 0, $Size, $Size)
$g.DrawImage($img, $destRect, $cx, $cy, $side, $side, [System.Drawing.GraphicsUnit]::Pixel)

$g.Dispose()
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
$img.Dispose()
$path.Dispose()
Write-Output "OK: wrote $Out ($Size x $Size, radius $Radius, crop R$CropRight B$CropBottom)"
