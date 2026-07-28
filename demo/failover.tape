# Kills the elected leader and shows ZooKeeper re-electing one.
#   vhs demo/failover.tape      (writes assets/demo-failover.gif)
# Requires the cluster to be running (make up).
Output assets/demo-failover.gif
Set Shell bash
Set FontSize 16
Set Width 900
Set Height 480
Set Padding 24
Set TypingSpeed 22ms
Set Framerate 24
Set Theme { "background": "#101219", "foreground": "#E4E7EC", "cursor": "#F7D473", "black": "#101219", "red": "#E9584A", "green": "#2CC0A6", "yellow": "#F7D473", "blue": "#6E8BD6", "magenta": "#B98BD6", "cyan": "#4FD6C8", "white": "#E4E7EC", "brightBlack": "#5A6272", "brightRed": "#FF9A80", "brightGreen": "#84F5DF", "brightYellow": "#FFE49B", "brightBlue": "#93A9E6", "brightMagenta": "#D0AEE6", "brightWhite": "#FFFFFF" }

Hide
Type "export PS1='$ '" Enter
Type "cd /Users/oriashkenazi/Documents/GitHub/codeguard" Enter
Type "clear" Enter
Sleep 500ms
Show

Type "make failover-test"
Enter
Sleep 42s
