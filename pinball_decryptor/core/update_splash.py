"""The window the user watches while Restart to update swaps versions
(PAD-1036).

David: "We should have a splash screen with a cool pinball animation on it
for the user to watch while they wait for the app to restart.  Otherwise,
they may think it's broken.  We need to show this after they press
'restart' and until the new app instance comes up.  Just like what discord
does."  And: "make the animation super clean and professional looking.
making it look good is a priority".

Between the click and the new version's window there was nothing on
screen: the app closes (its emulators and WSL shut down first, tens of
seconds on a slow PC), the swap helper renames the folders, launcher.vbs
raises the UAC prompt and the new app starts - or, on the installer route,
the setup exe copies a few hundred MB first.  So the click now opens this
window FIRST, before the app closes down, and the new version closes it the
moment its page is up (:func:`dismiss`, from Context.state_snapshot).

IT IS NOT A PYTHON WINDOW.  Anything running from ``<app>\\python`` holds
the folder open, and the swap's rename of that folder would fail on our own
splash ("a file in the app folder is still in use" - the same reason the
swap helper runs from the temp folder); the installer route's
/FORCECLOSEAPPLICATIONS would end it outright.  So, like the swap helper,
it is a PowerShell script written to the temp folder: a WPF window with the
playfield drawn and run by PowerShell itself.  Started the way the swap
helper is (CREATE_NO_WINDOW, never DETACHED_PROCESS: PAD-1029).

The playfield is a little game that plays itself, at 60 frames a second:
a ball under gravity with a shadow and a short trail, three pop bumpers
that glow and pulse when hit, slingshots, arrow inserts that light as the
ball passes, a score that counts, and two flippers that flip when the ball
comes down to them - and miss now and then, so the ball drains and is
plunged again.  A slim moving line under the table says the wait is alive
even when the ball is between plunges.

IT NEVER TRAPS THE USER.  Escape closes it at any time; after HINT_AFTER
seconds it says the new version opens by itself; after GIVE_UP_AFTER it
says how to start the app by hand and shows a Close button; after
CLOSE_AFTER it closes itself.
"""

import os
import subprocess
import sys
import tempfile

#: the window's title, which is how the new version finds it (FindWindow)
SPLASH_TITLE = "Pinball Asset Decryptor - updating"

#: seconds before the window says the new version opens by itself (the
#: installer route takes a minute or two: a normal wait, so a quiet word)
HINT_AFTER = 60
#: seconds before it says how to start the app by hand, with a Close button
GIVE_UP_AFTER = 300
#: seconds before it closes itself, whatever happened
CLOSE_AFTER = 900

WM_CLOSE = 0x0010


def _psq(text):
    """A PowerShell single-quoted string literal."""
    return "'" + str(text).replace("'", "''") + "'"


def _texts(version, tr):
    """The window's words, through the app's translator *tr* (English when
    None).  The product name is never translated."""
    tr = tr or (lambda t: t)
    return {
        "heading": "Pinball Asset Decryptor",
        "status": tr("Updating to v%s…" % version),
        "hint": tr("Still updating… the new version opens by itself "
                   "when it is ready."),
        "give_up": tr("This is taking longer than usual. If the app has not "
                      "opened, start it from its shortcut."),
        "close": tr("Close"),
    }


#: The window.  WPF from PowerShell: the XAML is the layout, the script the
#: game.  Values are substituted by :func:`splash_script`.  State lives in
#: one hashtable ($S) because a timer tick runs in its own scope, where a
#: plain assignment would make a local.  Table coordinates are a 400 x 210
#: space the Viewbox scales to the window.
_SPLASH_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
try { Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase } catch { exit 2 }
$S = @{}
$S.title = %(title_q)s
$S.heading = %(heading_q)s; $S.status = %(status_q)s
$S.hint = %(hint_q)s; $S.giveUp = %(give_up_q)s; $S.closeLabel = %(close_q)s
$S.cx = %(cx)d; $S.cy = %(cy)d; $S.placed = %(placed)s; $S.offscreen = %(offscreen)s
$S.hintAfter = %(hint_after)d; $S.giveUpAfter = %(give_up_after)d; $S.closeAfter = %(close_after)d
$S.hinted = $false; $S.gaveUp = $false

[xml]$xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Width="464" Height="354" WindowStyle="None" ResizeMode="NoResize"
        AllowsTransparency="True" Background="Transparent" ShowInTaskbar="True"
        WindowStartupLocation="CenterScreen" FontFamily="Segoe UI"
        TextOptions.TextFormattingMode="Display" TextOptions.TextRenderingMode="ClearType"
        RenderOptions.BitmapScalingMode="HighQuality">
  <Border Margin="12" CornerRadius="12" BorderBrush="#2E333B" BorderThickness="1">
    <Border.Background>
      <LinearGradientBrush StartPoint="0,0" EndPoint="0,1">
        <GradientStop Color="#1B1E24" Offset="0"/>
        <GradientStop Color="#15171A" Offset="1"/>
      </LinearGradientBrush>
    </Border.Background>
    <Border.Effect>
      <DropShadowEffect BlurRadius="14" ShadowDepth="2" Opacity="0.55" Color="#000000"/>
    </Border.Effect>
    <Grid>
      <Grid.RowDefinitions>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="*"/>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="Auto"/>
      </Grid.RowDefinitions>
      <StackPanel Grid.Row="0" Margin="20,16,20,4">
        <TextBlock Name="Heading" Foreground="#F4F5F7" FontSize="18" FontWeight="SemiBold"/>
        <TextBlock Name="Status" Foreground="#A3ABB6" FontSize="13" Margin="0,2,0,0"/>
      </StackPanel>
      <Viewbox Grid.Row="1" Margin="20,8,20,0" Stretch="Uniform">
        <Canvas Name="Table" Width="400" Height="210" ClipToBounds="True"/>
      </Viewbox>
      <Canvas Grid.Row="2" Name="Track" Height="3" Margin="20,10,20,0" ClipToBounds="True" Background="#262B33">
        <Rectangle Name="Runner" Width="90" Height="3">
          <Rectangle.Fill>
            <LinearGradientBrush StartPoint="0,0" EndPoint="1,0">
              <GradientStop Color="#00FFFFFF" Offset="0"/>
              <GradientStop Color="#4C8DFF" Offset="0.5"/>
              <GradientStop Color="#00FFFFFF" Offset="1"/>
            </LinearGradientBrush>
          </Rectangle.Fill>
        </Rectangle>
      </Canvas>
      <Grid Grid.Row="3" Margin="20,8,20,14" MinHeight="34">
        <TextBlock Name="Hint" Foreground="#A3ABB6" FontSize="12" TextWrapping="Wrap"
                   VerticalAlignment="Center" Margin="0,0,84,0"/>
        <Button Name="CloseBtn" HorizontalAlignment="Right" VerticalAlignment="Center"
                Padding="14,4" Visibility="Collapsed" Background="#2A2F36"
                Foreground="#F4F5F7" BorderBrush="#3A3F47" Cursor="Hand"/>
      </Grid>
    </Grid>
  </Border>
</Window>
'@
$reader = New-Object System.Xml.XmlNodeReader $xaml
$win = [Windows.Markup.XamlReader]::Load($reader)
$win.Title = $S.title
$win.FindName('Heading').Text = $S.heading
$win.FindName('Status').Text = $S.status
$S.hintBlock = $win.FindName('Hint')
$S.closeBtn = $win.FindName('CloseBtn')
$S.closeBtn.Content = $S.closeLabel
$S.closeBtn.Add_Click({ $win.Close() })
$S.runner = $win.FindName('Runner')
$S.track = $win.FindName('Track')
$win.Add_KeyDown({ if ($_.Key -eq 'Escape') { $win.Close() } })
$win.Add_MouseLeftButtonDown({ try { $win.DragMove() } catch {} })
if ($S.offscreen) {
  # the proof shots: off every screen, read back with PrintWindow
  $win.WindowStartupLocation = 'Manual'; $win.Left = -5000; $win.Top = 100
} elseif ($S.placed) {
  # centred on the app's window (its centre in device pixels), kept on the
  # desktop; a window with no place yet is centred on the main screen
  $win.WindowStartupLocation = 'Manual'
  $win.Add_SourceInitialized({
    try {
      $src = [System.Windows.PresentationSource]::FromVisual($win)
      $pt = $src.CompositionTarget.TransformFromDevice.Transform((New-Object System.Windows.Point($S.cx, $S.cy)))
      $l = $pt.X - $win.Width / 2; $t = $pt.Y - $win.Height / 2
      $vl = [System.Windows.SystemParameters]::VirtualScreenLeft; $vt = [System.Windows.SystemParameters]::VirtualScreenTop
      $vr = $vl + [System.Windows.SystemParameters]::VirtualScreenWidth; $vb = $vt + [System.Windows.SystemParameters]::VirtualScreenHeight
      $win.Left = [Math]::Max($vl, [Math]::Min($l, $vr - $win.Width))
      $win.Top = [Math]::Max($vt, [Math]::Min($t, $vb - $win.Height))
    } catch {}
  })
}

# ---------------------------------------------------------------- the table
$Table = $win.FindName('Table')   # not $T: PowerShell names are case-blind, and $t is a local below
function Col($hex) { return [System.Windows.Media.ColorConverter]::ConvertFromString($hex) }
function Brush($hex) { $b = New-Object System.Windows.Media.SolidColorBrush (Col $hex); $b.Freeze(); return $b }
function Grad($top, $bottom) {
  $g = New-Object System.Windows.Media.LinearGradientBrush
  $g.StartPoint = New-Object System.Windows.Point(0, 0); $g.EndPoint = New-Object System.Windows.Point(0, 1)
  $g.GradientStops.Add((New-Object System.Windows.Media.GradientStop ((Col $top), 0.0)))
  $g.GradientStops.Add((New-Object System.Windows.Media.GradientStop ((Col $bottom), 1.0)))
  $g.Freeze(); return $g
}
function Glow($hex, $radius, $opacity) {
  $fx = New-Object System.Windows.Media.Effects.DropShadowEffect
  $fx.Color = (Col $hex); $fx.BlurRadius = $radius; $fx.ShadowDepth = 0; $fx.Opacity = $opacity
  return $fx
}
function Place($shape, $x, $y) { [System.Windows.Controls.Canvas]::SetLeft($shape, $x); [System.Windows.Controls.Canvas]::SetTop($shape, $y) }
function Add-Shape($shape, $z) { $Table.Children.Add($shape) | Out-Null; [System.Windows.Controls.Panel]::SetZIndex($shape, $z) }
function Seg($x1, $y1, $x2, $y2, $kick) { return @{ x1 = [double]$x1; y1 = [double]$y1; x2 = [double]$x2; y2 = [double]$y2; kick = [double]$kick; shape = $null; hit = 0 } }
function Pts($list) { $pc = New-Object System.Windows.Media.PointCollection; foreach ($p in $list) { $pc.Add([System.Windows.Point]::new($p[0], $p[1])) }; return ,$pc }

# the table: a deep blue field with a soft light at the top, in a rail
$field = New-Object System.Windows.Shapes.Rectangle
$field.Width = 400; $field.Height = 210; $field.RadiusX = 16; $field.RadiusY = 16
$field.Fill = (Grad '#16294A' '#0B1526')
Add-Shape $field 0
$sheen = New-Object System.Windows.Shapes.Ellipse
$sheen.Width = 420; $sheen.Height = 160
$sb = New-Object System.Windows.Media.RadialGradientBrush
$sb.GradientStops.Add((New-Object System.Windows.Media.GradientStop ((Col '#2A4F8A'), 0.0)))
$sb.GradientStops.Add((New-Object System.Windows.Media.GradientStop ((Col '#0016294A'), 1.0)))
$sb.Freeze(); $sheen.Fill = $sb; $sheen.Opacity = 0.55
Place $sheen -10 -90
Add-Shape $sheen 1
$rail = New-Object System.Windows.Shapes.Rectangle
$rail.Width = 400; $rail.Height = 210; $rail.RadiusX = 16; $rail.RadiusY = 16
$rail.Stroke = (Brush '#3B5A8C'); $rail.StrokeThickness = 2.5
Add-Shape $rail 9

# the score, top right of the table
$score = New-Object System.Windows.Controls.TextBlock
$score.FontFamily = New-Object System.Windows.Media.FontFamily('Consolas'); $score.FontSize = 13
$score.Foreground = (Brush '#F2C230'); $score.Opacity = 0.9; $score.Text = '0'
$score.Width = 90; $score.TextAlignment = 'Right'
Place $score 294 10
Add-Shape $score 2
$S.scoreBlock = $score; $S.score = 0; $S.scoreShown = -1

# fixed walls: the outlane guides down to the flippers and the slingshots
$S.segs = @(
  (Seg 1 112 110 186 0), (Seg 399 112 290 186 0),
  (Seg 62 104 92 162 6), (Seg 338 104 308 162 6),
  (Seg 62 104 62 150 0), (Seg 62 150 92 162 0),
  (Seg 338 104 338 150 0), (Seg 338 150 308 162 0))
foreach ($g in $S.segs[0..1]) {
  $ln = New-Object System.Windows.Shapes.Line
  $ln.X1 = $g.x1; $ln.Y1 = $g.y1; $ln.X2 = $g.x2; $ln.Y2 = $g.y2
  $ln.Stroke = (Brush '#3B5A8C'); $ln.StrokeThickness = 3; $ln.StrokeStartLineCap = 'Round'; $ln.StrokeEndLineCap = 'Round'
  Add-Shape $ln 2
}
$slingPts = @(@(@(62, 104), @(62, 150), @(92, 162)), @(@(338, 104), @(338, 150), @(308, 162)))
for ($i = 0; $i -lt 2; $i++) {
  $sl = New-Object System.Windows.Shapes.Polygon
  $sl.Points = Pts $slingPts[$i]
  $sl.Fill = (Grad '#D9483B' '#8E2420'); $sl.Stroke = (Brush '#F7E7B0'); $sl.StrokeThickness = 2; $sl.StrokeLineJoin = 'Round'
  $sl.Effect = (Glow '#FF6A5A' 10 0.0)
  Add-Shape $sl 3
  $S.segs[2 + $i].shape = $sl
}

# arrow inserts: lit as the ball passes, fading after
$S.inserts = @()
$insertColors = @('#F2C230', '#F0613A', '#F2C230', '#F0613A', '#F2C230')
for ($i = 0; $i -lt 5; $i++) {
  $x = 120 + 40 * $i; $y = 130
  $a = New-Object System.Windows.Shapes.Polygon
  $a.Points = Pts @(@(0, 14), @(7, 0), @(14, 14))
  $a.Fill = (Brush $insertColors[$i]); $a.Stroke = (Brush '#0B1526'); $a.StrokeThickness = 0.8; $a.StrokeLineJoin = 'Round'
  $a.Opacity = 0.22; $a.Effect = (Glow $insertColors[$i] 12 0.0)
  Place $a ($x - 7) ($y - 7)
  Add-Shape $a 3
  $S.inserts += @{ x = [double]$x; y = [double]$y; e = $a; b = [double]0 }
}

# pop bumpers: body, rubber ring and lit cap, in a group that glows and
# pulses when the ball hits it
$S.bumpers = @()
$bumperSpec = @(@(130, 62, '#F04A3E', '#8C1E16'), @(200, 36, '#F7CF45', '#B07A12'), @(270, 62, '#4A94F0', '#1B4A96'))
foreach ($b in $bumperSpec) {
  $grp = New-Object System.Windows.Controls.Canvas
  $grp.Width = 40; $grp.Height = 40
  $grp.RenderTransformOrigin = New-Object System.Windows.Point(0.5, 0.5)
  $sc = New-Object System.Windows.Media.ScaleTransform(1.0, 1.0)
  $grp.RenderTransform = $sc
  $fx = Glow $b[2] 22 0.35
  $grp.Effect = $fx
  $body = New-Object System.Windows.Shapes.Ellipse
  $body.Width = 36; $body.Height = 36; $body.Fill = (Grad $b[2] $b[3])
  $body.Stroke = (Brush '#F7F7F7'); $body.StrokeThickness = 2.5
  Place $body 2 2; $grp.Children.Add($body) | Out-Null
  $ring = New-Object System.Windows.Shapes.Ellipse
  $ring.Width = 24; $ring.Height = 24; $ring.Stroke = (Brush '#33FFFFFF'); $ring.StrokeThickness = 1.5
  Place $ring 8 8; $grp.Children.Add($ring) | Out-Null
  $cap = New-Object System.Windows.Shapes.Ellipse
  $cap.Width = 14; $cap.Height = 14
  $cb = New-Object System.Windows.Media.RadialGradientBrush
  $cb.GradientOrigin = New-Object System.Windows.Point(0.35, 0.35)
  $cb.GradientStops.Add((New-Object System.Windows.Media.GradientStop ([System.Windows.Media.Colors]::White, 0.0)))
  $cb.GradientStops.Add((New-Object System.Windows.Media.GradientStop ((Col '#E6E9EE'), 0.6)))
  $cb.GradientStops.Add((New-Object System.Windows.Media.GradientStop ((Col '#AEB5BF'), 1.0)))
  $cb.Freeze(); $cap.Fill = $cb
  Place $cap 13 13; $grp.Children.Add($cap) | Out-Null
  Place $grp ($b[0] - 20) ($b[1] - 20)
  Add-Shape $grp 4
  $S.bumpers += @{ x = [double]$b[0]; y = [double]$b[1]; r = [double]18; scale = $sc; fx = $fx; hit = 0 }
}

# flippers: a tapered bat with a rubber edge, drawn from pivot and angle
$S.flippers = @()
foreach ($f in @(@(112, 186, 22, -30, 92, 205), @(288, 186, 158, 210, 195, 308))) {
  $bat = New-Object System.Windows.Shapes.Polygon
  $bat.Fill = (Grad '#F9DB62' '#D99A1E'); $bat.Stroke = (Brush '#8E5E0C'); $bat.StrokeThickness = 1.5; $bat.StrokeLineJoin = 'Round'
  $bat.Effect = (Glow '#000000' 8 0.5)
  Add-Shape $bat 6
  $piv = New-Object System.Windows.Shapes.Ellipse
  $piv.Width = 8; $piv.Height = 8; $piv.Fill = (Brush '#5A3C08')
  Place $piv ($f[0] - 4) ($f[1] - 4)
  Add-Shape $piv 7
  $S.flippers += @{ px = [double]$f[0]; py = [double]$f[1]; rest = [double]$f[2]; up = [double]$f[3]; ang = [double]$f[2]; len = [double]58; phase = 0; t = 0; bat = $bat; x1 = [double]$f[4]; x2 = [double]$f[5] }
}

# the ball: a shadow on the table, a short trail, and the ball itself
$S.shadow = New-Object System.Windows.Shapes.Ellipse
$S.shadow.Width = 18; $S.shadow.Height = 12; $S.shadow.Fill = (Brush '#000000'); $S.shadow.Opacity = 0.35
$S.shadow.Effect = (Glow '#000000' 6 0.8)
Add-Shape $S.shadow 5
$S.trail = @()
foreach ($spec in @(@(11, 0.30), @(9, 0.18), @(7, 0.09))) {
  $t = New-Object System.Windows.Shapes.Ellipse
  $t.Width = $spec[0]; $t.Height = $spec[0]; $t.Fill = (Brush '#DDE3EA'); $t.Opacity = $spec[1]
  Add-Shape $t 7
  $S.trail += $t
}
$S.history = New-Object System.Collections.ArrayList
$ball = New-Object System.Windows.Shapes.Ellipse
$ball.Width = 14; $ball.Height = 14
$gb = New-Object System.Windows.Media.RadialGradientBrush
$gb.GradientOrigin = New-Object System.Windows.Point(0.3, 0.3)
$gb.GradientStops.Add((New-Object System.Windows.Media.GradientStop ([System.Windows.Media.Colors]::White, 0.0)))
$gb.GradientStops.Add((New-Object System.Windows.Media.GradientStop ((Col '#C9CFD7'), 0.4)))
$gb.GradientStops.Add((New-Object System.Windows.Media.GradientStop ((Col '#4E545C'), 1.0)))
$gb.Freeze(); $ball.Fill = $gb
Add-Shape $ball 8
$S.ball = $ball
$S.rnd = New-Object System.Random
$S.x = 380.0; $S.y = 14.0; $S.vx = -2.5; $S.vy = 0.5; $S.r = 7.0; $S.wait = 0; $S.slow = 0

function Plunge {
  $S.x = 380.0; $S.y = 14.0; $S.vx = -(2.0 + 2.5 * $S.rnd.NextDouble()); $S.vy = 0.3; $S.slow = 0
  $S.history.Clear()
}
function BatPoints($f) {
  # the bat: a wide round end at the pivot, a narrow one at the tip (set on
  # the flipper itself: a collection returned would be unrolled)
  $a = $f.ang * [Math]::PI / 180.0
  $dx = [Math]::Cos($a); $dy = [Math]::Sin($a); $nx = -$dy; $ny = $dx
  $qx = $f.px + $f.len * $dx; $qy = $f.py + $f.len * $dy
  $rp = 7.0; $rt = 4.0
  $pts = New-Object System.Windows.Media.PointCollection
  for ($k = 0; $k -le 6; $k++) {
    $b = ($k / 6.0 - 0.5) * [Math]::PI
    $pts.Add([System.Windows.Point]::new(($qx + $rt * ([Math]::Cos($b) * $dx + [Math]::Sin($b) * $nx)), ($qy + $rt * ([Math]::Cos($b) * $dy + [Math]::Sin($b) * $ny))))
  }
  for ($k = 0; $k -le 6; $k++) {
    $b = ($k / 6.0 + 0.5) * [Math]::PI
    $pts.Add([System.Windows.Point]::new(($f.px + $rp * ([Math]::Cos($b) * $dx + [Math]::Sin($b) * $nx)), ($f.py + $rp * ([Math]::Cos($b) * $dy + [Math]::Sin($b) * $ny))))
  }
  $f.bat.Points = $pts; $f.ends = @($qx, $qy)
}
function Bounce($x1, $y1, $x2, $y2, $kick) {
  # the ball against the segment: pushed out and reflected when it overlaps
  $dx = $x2 - $x1; $dy = $y2 - $y1; $len2 = $dx * $dx + $dy * $dy
  if ($len2 -le 0) { return $false }
  $t = (($S.x - $x1) * $dx + ($S.y - $y1) * $dy) / $len2
  if ($t -lt 0) { $t = 0 } elseif ($t -gt 1) { $t = 1 }
  $px = $x1 + $t * $dx; $py = $y1 + $t * $dy
  $nx = $S.x - $px; $ny = $S.y - $py; $d = [Math]::Sqrt($nx * $nx + $ny * $ny)
  if ($d -ge $S.r + 1.5 -or $d -le 0.0001) { return $false }
  $nx = $nx / $d; $ny = $ny / $d
  $S.x = $px + $nx * ($S.r + 1.6); $S.y = $py + $ny * ($S.r + 1.6)
  $vn = $S.vx * $nx + $S.vy * $ny
  if ($vn -lt 0) { $S.vx = $S.vx - 1.6 * $vn * $nx; $S.vy = $S.vy - 1.6 * $vn * $ny }
  if ($kick -gt 0) { $S.vx = $S.vx + $nx * $kick; $S.vy = $S.vy + $ny * $kick }
  return $true
}

function Physics {
  # one half-step of the ball (two a frame: a fast ball never skips a bat)
  $S.vy = $S.vy + 0.07
  $S.x = $S.x + $S.vx * 0.5; $S.y = $S.y + $S.vy * 0.5
  # the rail
  if ($S.x -lt $S.r + 3) { $S.x = $S.r + 3; $S.vx = [Math]::Abs($S.vx) * 0.75 }
  if ($S.x -gt 397 - $S.r) { $S.x = 397 - $S.r; $S.vx = -[Math]::Abs($S.vx) * 0.75 }
  if ($S.y -lt $S.r + 3) { $S.y = $S.r + 3; $S.vy = [Math]::Abs($S.vy) * 0.75 }
  foreach ($b in $S.bumpers) {
    $dx = $S.x - $b.x; $dy = $S.y - $b.y; $d = [Math]::Sqrt($dx * $dx + $dy * $dy)
    if ($d -lt $b.r + $S.r -and $d -gt 0.0001) {
      $nx = $dx / $d; $ny = $dy / $d
      $S.x = $b.x + $nx * ($b.r + $S.r + 0.1); $S.y = $b.y + $ny * ($b.r + $S.r + 0.1)
      $vn = $S.vx * $nx + $S.vy * $ny
      if ($vn -lt 0) { $S.vx = $S.vx - 2 * $vn * $nx; $S.vy = $S.vy - 2 * $vn * $ny }
      $S.vx = $S.vx + $nx * 4.0; $S.vy = $S.vy + $ny * 4.0
      if ($b.hit -eq 0) { $S.score += 100 }
      $b.hit = 10
    }
  }
  # the walls and bats all lie in the lower half: a ball up in the bumpers
  # is not tested against them (the calls are what the frame costs)
  if ($S.y -gt 94) {
    foreach ($g in $S.segs) {
      if (Bounce $g.x1 $g.y1 $g.x2 $g.y2 $g.kick) { if ($g.kick -gt 0) { if ($g.hit -eq 0) { $S.score += 10 }; $g.hit = 8 } }
    }
  }
  if ($S.y -gt 150) {
    foreach ($f in $S.flippers) {
      $e = $f.ends
      $kick = 0; if ($f.phase -eq 1 -or $f.phase -eq 2) { $kick = 6.5 }
      if (Bounce $f.px $f.py $e[0] $e[1] $kick) { if ($kick -gt 0) { $S.vy = $S.vy - 2.0 } }
    }
  }
  $sp = [Math]::Sqrt($S.vx * $S.vx + $S.vy * $S.vy)
  if ($sp -gt 10.5) { $S.vx = $S.vx * 10.5 / $sp; $S.vy = $S.vy * 10.5 / $sp }
}

function Step {
  # the flippers: flip when the ball comes down over one
  foreach ($f in $S.flippers) {
    if ($f.phase -eq 0 -and $S.wait -eq 0 -and $S.vy -gt 0 -and $S.y -gt 148 -and $S.x -gt $f.x1 -and $S.x -lt $f.x2) { $f.phase = 1; $f.t = 0 }
    if ($f.phase -eq 1) { $f.t++; $f.ang = $f.rest + ($f.up - $f.rest) * $f.t / 5.0; if ($f.t -ge 5) { $f.phase = 2; $f.t = 0 } }
    elseif ($f.phase -eq 2) { $f.t++; $f.ang = $f.up; if ($f.t -ge 7) { $f.phase = 3; $f.t = 0 } }
    elseif ($f.phase -eq 3) { $f.t++; $f.ang = $f.up + ($f.rest - $f.up) * $f.t / 9.0; if ($f.t -ge 9) { $f.phase = 0; $f.ang = $f.rest } }
    if ($f.phase -ne 0 -or $null -eq $f.ends) { BatPoints $f }   # a bat at rest is not redrawn
  }
  if ($S.wait -gt 0) {
    $S.wait = $S.wait - 1; if ($S.wait -eq 0) { Plunge }
  } else {
    Physics; Physics
    $sp = [Math]::Sqrt($S.vx * $S.vx + $S.vy * $S.vy)
    if ($sp -lt 0.6) { $S.slow++ } else { $S.slow = 0 }
    if ($S.slow -gt 50) { $S.vy = $S.vy - 4; $S.vx = $S.vx + ($S.rnd.NextDouble() - 0.5) * 3; $S.slow = 0 }
    if ($S.y -gt 234) { $S.wait = 30; $S.y = 400; $S.history.Clear() }
  }
  # the lights
  foreach ($b in $S.bumpers) {
    if ($b.hit -gt 0) {
      $b.hit = $b.hit - 1; $k = $b.hit / 10.0
      $b.scale.ScaleX = 1 + 0.16 * $k; $b.scale.ScaleY = 1 + 0.16 * $k; $b.fx.Opacity = 0.35 + 0.65 * $k
    }
  }
  foreach ($g in $S.segs[2..3]) {
    if ($g.hit -gt 0) { $g.hit = $g.hit - 1; $g.shape.Effect.Opacity = $g.hit / 8.0 }
  }
  foreach ($n in $S.inserts) {
    $dx = $S.x - $n.x; $dy = $S.y - $n.y
    if ($dx * $dx + $dy * $dy -lt 420) { if ($n.b -lt 0.5) { $S.score += 50 }; $n.b = 1.0 }
    elseif ($n.b -gt 0.01) { $n.b = $n.b * 0.94 } else { $n.b = 0 }
    $n.e.Opacity = 0.22 + 0.78 * $n.b; $n.e.Effect.Opacity = $n.b
  }
  if ($S.score -ne $S.scoreShown) { $S.scoreShown = $S.score; $S.scoreBlock.Text = ('{0:N0}' -f $S.score) }
  # the ball, its shadow and its trail
  Place $S.ball ($S.x - $S.r) ($S.y - $S.r)
  Place $S.shadow ($S.x - 9 + 2) ($S.y - 6 + 5)
  $S.history.Insert(0, @($S.x, $S.y)) | Out-Null
  if ($S.history.Count -gt 7) { $S.history.RemoveAt(7) }
  for ($i = 0; $i -lt 3; $i++) {
    $idx = 2 * ($i + 1); $t = $S.trail[$i]
    if ($S.wait -eq 0 -and $idx -lt $S.history.Count) {
      $h = $S.history[$idx]; $t.Visibility = 'Visible'
      Place $t ($h[0] - $t.Width / 2) ($h[1] - $t.Height / 2)
    } else { $t.Visibility = 'Hidden' }
  }
  if ($S.wait -gt 0) { $S.shadow.Visibility = 'Hidden' } else { $S.shadow.Visibility = 'Visible' }
}

$S.clock = [System.Diagnostics.Stopwatch]::StartNew()
$timer = New-Object System.Windows.Threading.DispatcherTimer
$timer.Interval = [TimeSpan]::FromMilliseconds(16)
$timer.Add_Tick({
  try { Step } catch {}
  $t = $S.clock.Elapsed.TotalSeconds
  # the moving line under the table
  $w = $S.track.ActualWidth; if ($w -gt 0) { [System.Windows.Controls.Canvas]::SetLeft($S.runner, (($t * 170) %% ($w + 90)) - 90) }
  if (-not $S.hinted -and $t -ge $S.hintAfter) { $S.hinted = $true; $S.hintBlock.Text = $S.hint }
  if (-not $S.gaveUp -and $t -ge $S.giveUpAfter) { $S.gaveUp = $true; $S.hintBlock.Text = $S.giveUp; $S.closeBtn.Visibility = 'Visible' }
  if ($t -ge $S.closeAfter) { $win.Close() }
})
$win.Add_Loaded({ $timer.Start() })
$win.Add_Closed({ $timer.Stop() })
$win.ShowDialog() | Out-Null
Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
exit 0
"""


def splash_script(version, center=None, tr=None, title=SPLASH_TITLE,
                  hint_after=HINT_AFTER, give_up_after=GIVE_UP_AFTER,
                  close_after=CLOSE_AFTER, offscreen=False):
    """The PowerShell text of the splash window (see module docstring).
    *center* is the app window's centre in device pixels, or None for the
    middle of the main screen."""
    words = _texts(version, tr)
    cx, cy = center if center else (0, 0)
    return _SPLASH_SCRIPT % {
        "title_q": _psq(title), "heading_q": _psq(words["heading"]),
        "status_q": _psq(words["status"]), "hint_q": _psq(words["hint"]),
        "give_up_q": _psq(words["give_up"]), "close_q": _psq(words["close"]),
        "cx": int(cx), "cy": int(cy),
        "placed": "$true" if center else "$false",
        "offscreen": "$true" if offscreen else "$false",
        "hint_after": int(hint_after), "give_up_after": int(give_up_after),
        "close_after": int(close_after)}


def start_splash(version, center=None, tr=None, title=SPLASH_TITLE,
                 popen=None, platform=None, **timing):
    """Open the splash for an update to *version*.  Returns ``(True,
    process)`` or ``(False, reason)``; never raises.

    Windows only (the swap and the installer are), and never a second one
    while one is up (a second Restart click, PAD-1034).  Written to and
    started from the temp folder, like the swap helper and for the same
    reason: nothing of it may be in the app's folder, which is about to be
    renamed.  CREATE_NO_WINDOW, not DETACHED_PROCESS (PAD-1029: Windows
    PowerShell with no console at all runs nothing); -STA for WPF.
    """
    if (platform or sys.platform) != "win32":
        return False, "only on Windows"
    if find_window(title):
        return False, "already showing"
    popen = popen or subprocess.Popen
    tmp = tempfile.gettempdir()
    fd, script = tempfile.mkstemp(prefix="pad-splash-", suffix=".ps1",
                                  dir=tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="\r\n") as f:
            f.write(splash_script(version, center=center, tr=tr, title=title,
                                  **timing))
        flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                 | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        proc = popen(["powershell.exe", "-NoProfile", "-NonInteractive",
                      "-STA", "-ExecutionPolicy", "Bypass", "-WindowStyle",
                      "Hidden", "-File", script], cwd=tmp,
                     creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
    except Exception as e:                                  # noqa: BLE001
        try:
            os.unlink(script)
        except OSError:
            pass
        return False, str(e)
    return True, proc


def find_window(title=SPLASH_TITLE):
    """The splash window's handle, or 0 when none is up (always 0 off
    Windows)."""
    if sys.platform != "win32":
        return 0
    import ctypes
    try:
        return ctypes.windll.user32.FindWindowW(None, title) or 0
    except Exception:                                       # noqa: BLE001
        return 0


def dismiss(title=SPLASH_TITLE):
    """Close the splash: the new version is up.  True when one was there.
    Called on every start (Context.state_snapshot) - a FindWindow when
    there is none, so it costs nothing."""
    hwnd = find_window(title)
    if not hwnd:
        return False
    import ctypes
    try:
        ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    except Exception:                                       # noqa: BLE001
        return False
    return True
