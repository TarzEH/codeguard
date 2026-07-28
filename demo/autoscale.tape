# Shows the autoscaler growing the cluster under load and releasing it after.
#   vhs demo/autoscale.tape     (writes assets/demo-autoscale.gif)
# Prerequisites: cluster at 1 replica with the autoscaler running, e.g.
#   docker compose up -d --no-deps --no-recreate --scale backend=1 backend
#   AUTOSCALE_INTERVAL=5 AUTOSCALE_COOLDOWN=10 docker compose --profile autoscale up -d
Output assets/demo-autoscale.gif
Set Shell bash
Set FontSize 16
Set Width 820
Set Height 720
Set Padding 24
Set TypingSpeed 22ms
Set Framerate 20
Set Theme { "background": "#101219", "foreground": "#E4E7EC", "cursor": "#F7D473", "black": "#101219", "red": "#E9584A", "green": "#2CC0A6", "yellow": "#F7D473", "blue": "#6E8BD6", "magenta": "#B98BD6", "cyan": "#4FD6C8", "white": "#E4E7EC", "brightBlack": "#5A6272", "brightRed": "#FF9A80", "brightGreen": "#84F5DF", "brightYellow": "#FFE49B", "brightBlue": "#93A9E6", "brightMagenta": "#D0AEE6", "brightWhite": "#FFFFFF" }

Hide
Type "export PS1='$ '" Enter
Type "cd /Users/oriashkenazi/Documents/GitHub/codeguard" Enter
Type "clear" Enter
Sleep 500ms
Show

Type "./demo/autoscale-demo.sh"
Enter
Sleep 160s
