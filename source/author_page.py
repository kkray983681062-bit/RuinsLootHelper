"""The author's statement approved for the application."""
import tkinter as tk
from ui_theme import BG, FG, MUTED, GOLD, label
from overlay_scroll import AutoScrollbar

AUTHOR_TEXT = '''做这个助手，最开始就是因为红词条看得太累了。

我喜欢暗黑类游戏，喜欢刷装备，也喜欢研究词条和配装。但现在能玩游戏的时间有限，眼睛也容易累。好不容易有空刷一会儿，还得停下来，一件件看背包里的装备，就想着做个小工具，帮我把值得留下的东西挑出来，再告诉我装备在哪。

所以最初只有装备筛选和背包定位。后来自己边玩边用，碰到不方便的地方就改一点，功能慢慢越加越多，最后成了现在这样。

不过，我最希望大家使用的，还是装备筛选和背包定位。这也是我一开始真正想解决的问题：少费点眼睛，少花点时间翻背包。

后面那些需要游戏组件的进阶功能，我其实不太希望大家用。它们确实方便，但也在提前消费这款游戏的寿命。作者花心思设计的探索、成长和游戏节奏，被工具跳过了。作为一个喜欢这款游戏的人，我知道，这样做是对游戏作者的不尊重。

做这些功能，说到底是我自己时间有限，又想图方便。但这是我的私心，不能因为省了时间，就把它们都当成对游戏有帮助的东西。好不容易找到一个喜欢的游戏，我也不希望这些便利最后让大家更快失去兴趣。

尤其是刚接触游戏的朋友，我建议先正常玩一段时间。自己认识地图、研究装备、尝试搭配，走点弯路也没关系。这些过程本来就是游戏的一部分，也值得花时间体验。自动开门设置使用门槛，也是希望它主要用于老玩家已经熟悉的重复操作，而不是让新玩家一开始就跳过正常体验。

至于封印之地的入口提示，就没什么好解释的了，纯粹是我自己懒。刷了几千次，找门还是费劲，干脆做个提示，自己省事，也方便有同样困扰的朋友。

这个助手免费、开源。主要就是分享给同样喜欢这个游戏、喜欢暗黑、愿意为了装备和词条反复刷的玩家。大家都有自己的事情要忙，能一直留着这么个爱好，我觉得挺难得。

我希望它能给大家提供一点便利，让有限的游戏时间玩得轻松一些。但也希望大家用得节制，给游戏作者的设计留一点耐心。少一点重复操作之后，仍然愿意研究一套配装，仍然会为刷到一件好装备高兴，这才是我希望看到的。'''


def populate(parent):
    label(parent, '作者的话', size=21, bold=True).pack(anchor='w', pady=(8, 6))
    label(parent, '一点便利，也希望大家用得节制。', color=MUTED).pack(anchor='w', pady=(0, 18))
    body = tk.Frame(parent, bg=BG)
    body.pack(fill='both', expand=True)
    text = tk.Text(body, bg=BG, fg=FG, relief='flat', borderwidth=0, highlightthickness=0,
                   wrap='word', padx=4, pady=4, spacing1=4, spacing3=14,
                   font=('Microsoft YaHei UI', 11), insertbackground=FG)
    scrollbar = AutoScrollbar(body, text)
    text.pack(fill='both', expand=True)
    text.insert('1.0', AUTHOR_TEXT)
    text.configure(state='disabled')
    return scrollbar
