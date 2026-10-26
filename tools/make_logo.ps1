param(
    [string]$Out,
    [int]$S = 1024
)

# Draw the WiFi-IP-Locator logo programmatically (no AI generation):
# brand-blue full-bleed square + white WiFi fan arcs + brand-green dot.
# Pipe the result through make_rounded.ps1 to get the rounded-corner mask.
Add-Type -AssemblyName System.Drawing

$bmp = New-Object System.Drawing.Bitmap($S, $S)
$bmp.SetResolution(96, 96)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality

# full-bleed brand blue square (rounding is applied later by make_rounded.ps1)
$blue = [System.Drawing.Color]::FromArgb(255, 0x1C, 0x4D, 0x9F)
$green = [System.Drawing.Color]::FromArgb(255, 0x93, 0xC9, 0x3E)
$white = [System.Drawing.Color]::White
$bg = New-Object System.Drawing.SolidBrush($blue)
$g.FillRectangle($bg, 0, 0, $S, $S)
$bg.Dispose()

$cx = [double]($S * 0.5)
$baseY = [double]($S * 0.7)   # fan origin (the dot center)

# three white arcs, round caps
$pen = New-Object System.Drawing.Pen($white, [single]($S * 0.055))
$pen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
$pen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
foreach ($r in @(0.15, 0.28, 0.41)) {
    $rad = $S * $r
    $rect = New-Object System.Drawing.RectangleF(
        [single]($cx - $rad), [single]($baseY - $rad),
        [single](2 * $rad), [single](2 * $rad))
    # 225..315 deg = the upward-opening fan
    $g.DrawArc($pen, $rect, 225, 90)
}
$pen.Dispose()

# brand-green center dot
$dotR = $S * 0.045
$dotBrush = New-Object System.Drawing.SolidBrush($green)
$dotRect = New-Object System.Drawing.RectangleF(
    [single]($cx - $dotR), [single]($baseY - $dotR),
    [single](2 * $dotR), [single](2 * $dotR))
$g.FillEllipse($dotBrush, $dotRect)
$dotBrush.Dispose()

$g.Dispose()
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
Write-Output "OK: wrote $Out ($S x $S)"
