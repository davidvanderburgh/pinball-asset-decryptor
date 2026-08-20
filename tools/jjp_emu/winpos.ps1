# Read or set a WSLg window's position, by title.
#
# WHY THIS EXISTS.  The game runs inside a nested Xephyr server, and Xephyr's
# own window is an ordinary window on the Windows desktop.  Nothing remembers
# where that window was: Xephyr cannot position itself (its -screen +X+Y and
# -origin place a screen inside the VIRTUAL X screen, not the host window), the
# game has no say, and WSLg does not persist it.  So every launch put the game
# back wherever the compositor felt like - on a multi-monitor desktop, usually
# the wrong monitor.
#
# WHY ENUMWINDOWS AND NOT Get-Process.  WSLg windows are RAIL windows hosted by
# msrdc.exe.  A process exposes ONE MainWindowTitle, so `Get-Process` shows
# exactly one WSLg window no matter how many are open - with the matrix and the
# game both up, whichever it picks is a coin toss.  EnumWindows sees every
# top-level window, which is the only way to address a specific one.
#
# WHY NOT xdotool/wmctrl.  Neither is installed, both would be new apt
# dependencies for the rig, and the window is a WINDOWS window - moving it from
# the X side means asking Weston to ask Windows, which is a longer road to the
# same SetWindowPos.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('get', 'set')][string]$Action,
    [Parameter(Mandatory = $true)][string]$Pattern,
    [int]$X = 0, [int]$Y = 0, [int]$W = 0, [int]$H = 0
)

$ErrorActionPreference = 'Stop'

Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class JjpWin {
  public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
  [DllImport("user32.dll")] public static extern int GetWindowTextLength(IntPtr h);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

# A fresh list per call - a script-scoped accumulator leaks between calls and
# reports the previous search's hits as this one's.
$hits = New-Object System.Collections.ArrayList
$cb = [JjpWin+EnumProc] {
    param($h, $l)
    if ([JjpWin]::IsWindowVisible($h)) {
        $len = [JjpWin]::GetWindowTextLength($h)
        if ($len -gt 0) {
            $sb = New-Object System.Text.StringBuilder ($len + 1)
            [void][JjpWin]::GetWindowText($h, $sb, $sb.Capacity)
            $t = $sb.ToString()
            if ($t -like $Pattern) {
                $r = New-Object JjpWin+RECT
                if ([JjpWin]::GetWindowRect($h, [ref]$r)) {
                    [void]$hits.Add([PSCustomObject]@{
                        Handle = $h; Title = $t
                        X = $r.Left; Y = $r.Top
                        W = $r.Right - $r.Left; H = $r.Bottom - $r.Top
                    })
                }
            }
        }
    }
    return $true
}
[void][JjpWin]::EnumWindows($cb, [IntPtr]::Zero)

if ($hits.Count -eq 0) { Write-Output 'none'; exit 2 }
$win = $hits[0]

if ($Action -eq 'get') {
    # key=value, the same shape status.sh speaks, so the caller never parses prose.
    Write-Output ("x={0}" -f $win.X)
    Write-Output ("y={0}" -f $win.Y)
    Write-Output ("w={0}" -f $win.W)
    Write-Output ("h={0}" -f $win.H)
    Write-Output ("title={0}" -f $win.Title)
    exit 0
}

# set.  SWP_NOZORDER|SWP_NOACTIVATE - move it without raising it over whatever
# the user is actually looking at, and without stealing focus.
$flags = 0x0004 -bor 0x0010
if ($W -le 0 -or $H -le 0) {
    $flags = $flags -bor 0x0001          # SWP_NOSIZE - position only
    $W = 0; $H = 0
}
$ok = [JjpWin]::SetWindowPos($win.Handle, [IntPtr]::Zero, $X, $Y, $W, $H, $flags)
if (-not $ok) { Write-Output 'failed'; exit 3 }
Write-Output ("moved to {0},{1} {2}x{3}" -f $X, $Y, $W, $H)
exit 0
