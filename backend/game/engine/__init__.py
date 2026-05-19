# 卡牌系統 
from .cards import (
    # 列舉類型
    CardType,
    CardColor,

    # 協議介面
    GameContext,

    # 命令模式
    PlayCardCommand,

    # 抽象基類
    AbstractCard,

    # 具體卡牌類別
    NumberCard,
    SkipCard,
    ReverseCard,
    Draw2Card,
    WildCard,
    WildDraw4Card,
    SwapHandCard,
    StealCardCard,
    NeighborSwapCard,
    TargetDraw2Card,

    # 工廠類別
    DeckFactory,

    # 便利函式
    create_standard_deck,
)

# 技能系統
from .skills import (
    # 協議介面
    SkillContext,

    # 抽象基類
    SkillBehavior,

    # 具體技能類別
    SeerSkill,
    PainterSkill,
    ScoutSkill,
    QueenSkill,

    # 工廠類別
    SkillFactory,
)

# 玩家管理
from .player import (
    HandManager,
    Player,
)

# 遊戲引擎
from .game_engine import (
    GamePhase,
    GameEngine,
)

# 遊戲狀態
from .game_state import (
    PlayerState,
    GameState,
    PlayerHandState,
    GameAction,
    GameHistory,
)

# 公開 API
__all__ = [
    # 卡牌系統
    'CardType',
    'CardColor',
    'GameContext',
    'PlayCardCommand',
    'AbstractCard',
    'NumberCard',
    'SkipCard',
    'ReverseCard',
    'Draw2Card',
    'WildCard',
    'WildDraw4Card',
    'SwapHandCard',
    'StealCardCard',
    'NeighborSwapCard',
    'TargetDraw2Card',
    'DeckFactory',
    'create_standard_deck',

    # 技能系統
    'SkillContext',
    'SkillBehavior',
    'SeerSkill',
    'PainterSkill',
    'ScoutSkill',
    'QueenSkill',
    'SkillFactory',

    # 玩家管理
    'HandManager',
    'Player',

    # 遊戲引擎
    'GamePhase',
    'GameEngine',

    # 遊戲狀態
    'PlayerState',
    'GameState',
    'PlayerHandState',
    'GameAction',
    'GameHistory',
]
