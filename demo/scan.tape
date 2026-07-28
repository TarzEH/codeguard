# Hero demo for the README: scan a project, get actionable output.
#   vhs demo/scan.tape          (writes assets/demo-scan.gif)
# Requires the cluster to be running (make up) and the cache warmed once.
# ASCII only inside Type.
Output assets/demo-scan.gif
Set Shell bash
Set FontSize 17
Set Width 940
Set Height 860
Set Padding 24
Set TypingSpeed 22ms
Set Framerate 24
Set Theme { "background": "#101219", "foreground": "#E4E7EC", "cursor": "#F7D473", "black": "#101219", "red": "#E9584A", "green": "#2CC0A6", "yellow": "#F7D473", "blue": "#6E8BD6", "magenta": "#B98BD6", "cyan": "#4FD6C8", "white": "#E4E7EC", "brightBlack": "#5A6272", "brightRed": "#FF9A80", "brightGreen": "#84F5DF", "brightYellow": "#FFE49B", "brightBlue": "#93A9E6", "brightMagenta": "#D0AEE6", "brightWhite": "#FFFFFF" }

Hide
Type "export PS1='$ '" Enter
Type "export PATH=/private/tmp/claude-501/-Users-oriashkenazi-Documents-GitHub-codeguard/40147cbe-f7fa-4581-b1e8-29e8163844f4/scratchpad/vbin:$PATH" Enter
Type "cd /Users/oriashkenazi/Documents/GitHub/codeguard/demo/sample-project" Enter
Type "clear" Enter
Sleep 500ms
Show

Type "cat requirements.txt"
Enter
Sleep 2s

Type "codeguard"
Enter
Sleep 7s

Type "echo $?"
Enter
Sleep 3s
