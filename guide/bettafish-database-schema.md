# BettaFish 数据源 Schema 设计深度解析

> 基于 `MindSpider/DeepSentimentCrawling/MediaCrawler/database/models.py` 完整源码分析
> 以及 `MindSpider/schema/mindspider_tables.sql` 和 `InsightEngine/tools/search.py` 验证

---

## 目录

1. [核心结论：Schema 统一性分析](#一核心结论schema-统一性分析)
2. [数据库整体架构](#二数据库整体架构)
3. [各平台内容表 Schema 逐表解析](#三各平台内容表-schema-逐表解析)
4. [各平台评论表 Schema 逐表解析](#四各平台评论表-schema-逐表解析)
5. [用户/创作者表 Schema](#五用户创作者表-schema)
6. [MindSpider 扩展表（话题发现层）](#六mindspider-扩展表话题发现层)
7. [Schema 异构性分析：为什么每个平台都不同](#七schema-异构性分析为什么每个平台都不同)
8. [统一抽象层设计：`_extract_engagement` 如何抹平差异](#八统一抽象层设计_extract_engagement-如何抹平差异)
9. [时间字段异构问题与解决方案](#九时间字段异构问题与解决方案)
10. [索引设计分析](#十索引设计分析)
11. [Schema 扩展字段（MindSpider 增强）](#十一schema-扩展字段mindspider-增强)
12. [新项目 Schema 设计建议](#十二新项目-schema-设计建议)

---

## 一、核心结论：Schema 统一性分析

### 答：每个平台的 Schema 都不同，且有意为之

BettaFish 的数据层采用了**平台原生字段设计**策略——每个平台保留其原始字段命名，而不是强行统一。这种设计是**刻意的**，原因有三：

1. **平台 API 字段原生性**：各平台的爬虫直接对应平台返回的 JSON 字段名（如 B 站的 `video_comment`、抖音的 `comment_count`），强行重命名会丢失可追溯性
2. **业务完整性保留**：不同平台有独特字段（如 B 站的 `video_danmaku` 弹幕数、快手的 `video_play_url` 播放地址），统一 Schema 会导致信息丢失
3. **统一抽象层在查询层解决**：在 `MediaCrawlerDB` 的 `_extract_engagement()` 方法中做字段归一化，在 Agent 的 Prompt 层做平台差异化分析

### Schema 异构程度对比

| 对比维度 | 内容表 | 评论表 | 创作者表 |
|---|---|---|---|
| **表数量** | 7 张（各平台独立） | 7 张（各平台独立） | 7 张（各平台独立） |
| **字段数量** | 17–22 个/表 | 12–17 个/表 | 8–15 个/表 |
| **主键命名** | 各自独立（`video_id`/`aweme_id`/`note_id` 等） | 各自独立 | 各自独立 |
| **参与度字段** | **完全不同** | **完全不同** | N/A |
| **时间字段** | **3 种格式**（Unix ms / Unix sec / ISO str） | **3 种格式** | 2 种格式 |
| **IP 字段** | 部分平台有 | 部分平台有 | 部分平台有 |
| **搜索关键字字段** | ✅ 全部有 | ❌ 全部无 | ❌ 部分有 |

---

## 二、数据库整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                   MySQL / PostgreSQL                             │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │         MediaCrawler 层（7平台 × 3表 = 21张表）        │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │   │
│  │  │bilibili │ │ weibo    │ │ douyin   │ │ kuaishou │    │   │
│  │  │_video   │ │ _note    │ │ _aweme   │ │ _video   │    │   │
│  │  │_comment │ │ _comment │ │ _comment │ │ _comment │    │   │
│  │  │_upinfo │ │ _creator │ │ _creator │ │          │    │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘    │   │
│  │  ┌──────────┐ ┌──────────┐                               │   │
│  │  │  xhs    │ │ zhihu   │ ┌──────────┐                 │   │
│  │  │ _note   │ │ _content│ │ tieba   │                 │   │
│  │  │ _comment │ │ _comment│ │ _note   │                 │   │
│  │  │ _creator│ │ _creator│ │ _comment│                 │   │
│  │  └──────────┘ └──────────┘ │ _creator│                 │   │
│  │                          └──────────┘                 │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │       MindSpider 层（4张扩展表）                           │   │
│  │  daily_news ──→ daily_topics ──→ topic_news_relation    │   │
│  │                ──→ crawling_tasks                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │       视图层（2个分析视图）                                │   │
│  │  v_topic_crawling_stats / v_daily_summary                │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 三、各平台内容表 Schema 逐表解析

### 3.1 B站视频表 `bilibili_video`

```sql
CREATE TABLE bilibili_video (
    id                      INTEGER PRIMARY KEY,
    video_id               BIGINT  UNIQUE INDEX,  -- B站视频唯一ID (BV号)
    video_url              TEXT    NOT NULL,      -- 视频播放页URL
    user_id                BIGINT  INDEX,         -- UP主UID
    nickname               TEXT,                  -- UP主昵称
    avatar                 TEXT,                  -- UP主头像URL
    liked_count            INTEGER,               -- 点赞数 ←───── 基础认可
    video_play_count       TEXT,                  -- 播放量 ←───── 曝光基数（Text类型！）
    video_favorite_count   TEXT,                  -- 收藏数 ←───── 长期价值
    video_share_count      TEXT,                  -- 分享数 ←───── 传播意愿
    video_coin_count       TEXT,                  -- 投币数 ←───── 深度认可
    video_danmaku          TEXT,                  -- 弹幕数 ←───── 实时互动
    video_comment          TEXT,                  -- 评论数 ←───── 讨论深度
    title                  TEXT,                  -- 视频标题
    desc                   TEXT,                  -- 视频简介
    create_time            BIGINT  INDEX,         -- 发布时间（Unix 秒）
    video_type             TEXT,                  -- 视频类型
    disliked_count         TEXT,                  -- 点踩数
    video_cover_url        TEXT,                  -- 封面图URL
    source_keyword         TEXT    DEFAULT '',    -- 爬取时的搜索关键词
    add_ts                 BIGINT,                -- 记录入库时间
    last_modify_ts         BIGINT                 -- 记录最后修改时间
)
```

**特点分析**：
- B站参与度字段**全部是 TEXT 类型**（其他平台也类似），需要在 SQL 中 CAST
- 特有的 `video_danmaku`（弹幕）和 `video_coin_count`（投币）是其独特优势
- 热度公式中弹幕权重仅 0.5，体现了「弹幕是噪音信号」的工程判断

### 3.2 微博帖子表 `weibo_note`

```sql
CREATE TABLE weibo_note (
    id                      INTEGER PRIMARY KEY,
    note_id                BIGINT  UNIQUE INDEX,  -- 微博帖子唯一ID
    content                 TEXT,                  -- 帖子正文 ←───── 主要内容
    nickname                TEXT,                  -- 发帖用户昵称
    gender                  TEXT,                  -- 性别
    profile_url             TEXT,                  -- 用户主页URL
    ip_location             TEXT     DEFAULT '',   -- IP属地 ←───── 地理分析核心
    liked_count            TEXT,                  -- 点赞数
    comments_count          TEXT,                  -- 评论数
    shared_count           TEXT,                  -- 转发数 ←───── 传播核心指标
    note_url               TEXT,                  -- 帖子URL
    create_time            BIGINT  INDEX,         -- 发布时间（Unix 秒）
    create_date_time       VARCHAR(255) INDEX,    -- 发布时间（可读格式）←─ 特殊！
    user_id                VARCHAR(255),         -- 用户ID
    avatar                  TEXT,
    add_ts                 BIGINT,
    last_modify_ts         BIGINT,
    source_keyword         TEXT    DEFAULT ''
)
```

**特点分析**：
- `create_date_time` 是**微博独有**的字符串格式时间字段（`"2025-08-22 14:30:00"`）
- 帖子内容就是 `content`（非 B 站的 `title`+`desc` 结构），更接近小红书的「笔记」
- `shared_count`（转发）> `comments_count`（评论），传播路径以转发为主

### 3.3 抖音短视频表 `douyin_aweme`

```sql
CREATE TABLE douyin_aweme (
    id                      INTEGER PRIMARY KEY,
    aweme_id               BIGINT  UNIQUE INDEX,  -- 抖音视频ID
    user_id                VARCHAR(255),           -- 创作者ID
    sec_uid                VARCHAR(255),          -- 加密用户ID
    short_user_id          VARCHAR(255),
    user_unique_id          VARCHAR(255),
    nickname                TEXT,                  -- 创作者昵称
    avatar                  TEXT,
    user_signature          TEXT,                  -- 创作者签名
    ip_location             TEXT,                  -- IP属地 ←───── 地理扩散分析
    liked_count            TEXT,                  -- 点赞数
    comment_count          TEXT,                  -- 评论数
    share_count            TEXT,                  -- 分享数
    collected_count        TEXT,                  -- 收藏数
    aweme_type             TEXT,                  -- 视频类型
    title                  TEXT,                  -- 视频标题
    desc                   TEXT,                  -- 视频描述
    create_time            BIGINT  INDEX,         -- 发布时间（Unix **毫秒**）←─ 与B站不同！
    aweme_url              TEXT,                  -- 视频播放页URL
    cover_url              TEXT,                  -- 封面URL
    video_download_url     TEXT,
    music_download_url     TEXT,
    note_download_url     TEXT,
    source_keyword         TEXT    DEFAULT '',
    add_ts                 BIGINT,
    last_modify_ts         BIGINT
)
```

**特点分析**：
- `create_time` 是 **Unix 毫秒**（其他平台是秒），必须在 `_to_datetime()` 中特殊处理
- `ip_location` 字段用于地理扩散速度分析

### 3.4 小红书笔记表 `xhs_note`

```sql
CREATE TABLE xhs_note (
    id                      INTEGER PRIMARY KEY,
    note_id                VARCHAR(255) UNIQUE INDEX, -- 笔记ID
    type                   TEXT,                  -- 笔记类型（图文/视频）
    title                  TEXT,                  -- 笔记标题
    desc                   TEXT,                  -- 笔记正文
    image_list             TEXT,                  -- 图片列表（JSON格式）
    time                   BIGINT  INDEX,         -- 发布时间（Unix **毫秒**）←─ 与抖音相同
    last_update_time       BIGINT,                -- 最后更新时间
    liked_count            TEXT,                  -- 点赞数
    collected_count        TEXT,                  -- 收藏数
    comment_count          TEXT,                  -- 评论数
    share_count            TEXT,                  -- 分享数
    tag_list               TEXT,                  -- 标签列表（JSON格式）←─ 小红书独有
    note_url               TEXT,                  -- 笔记URL
    xsec_token             TEXT,                  -- 安全Token
    ip_location            TEXT,                  -- IP属地
    source_keyword         TEXT    DEFAULT '',
    user_id, nickname, avatar, add_ts, last_modify_ts ...
)
```

**特点分析**：
- 特有的 `tag_list`（JSON 格式标签）和 `image_list`（图片 URL 列表）
- `tag_list` 被 `search_topic_globally` 的搜索配置覆盖：`['title', 'desc', 'tag_list', 'source_keyword']`
- 视频笔记有 `video_url` 字段（复用字段名）

### 3.5 快手视频表 `kuaishou_video`

```sql
CREATE TABLE kuaishou_video (
    id                      INTEGER PRIMARY KEY,
    video_id               VARCHAR(255) UNIQUE INDEX,
    video_type             TEXT,
    title                  TEXT,                  -- 视频标题
    desc                   TEXT,                  -- 视频描述
    create_time            BIGINT  INDEX,         -- 发布时间（Unix **毫秒**）←─ 与抖音/小红书相同
    liked_count            TEXT,                  -- 点赞数
    viewd_count            TEXT,                  -- 播放量 ←───── 只有播放量，无评论/分享字段！
    video_url, video_cover_url, video_play_url TEXT,
    source_keyword         TEXT    DEFAULT '',
    user_id, nickname, avatar, add_ts, last_modify_ts ...
)
```

**特点分析**：
- 快手的严重缺陷：**没有** `share_count`（分享）和 `comment_count`（评论）字段
- 热度公式只能退化为：`hotness = liked_count×1 + viewd_count×0.1`
- 这导致快手在跨平台热度排名中天然劣势

### 3.6 知乎内容表 `zhihu_content`

```sql
CREATE TABLE zhihu_content (
    id                      INTEGER PRIMARY KEY,
    content_id              VARCHAR(64) INDEX,     -- 内容ID
    content_type            TEXT,                  -- 类型：answer/article/zvideo
    content_text             TEXT,                  -- 正文内容
    content_url             TEXT,                  -- 内容落地页URL
    question_id             VARCHAR(255),          -- 所属问题ID（回答类型时）
    title                   TEXT,                  -- 标题
    desc                    TEXT,                  -- 描述/摘要
    created_time            VARCHAR(32) INDEX,    -- 发布时间（**Unix 秒字符串**）←─ 特殊！
    updated_time            TEXT,
    voteup_count            INTEGER DEFAULT 0,   -- 赞同数 ←───── 知乎「点赞」叫 voteup
    comment_count           INTEGER DEFAULT 0,   -- 评论数
    source_keyword         TEXT,
    user_id, user_link, user_nickname,          -- 用户信息
    user_avatar, user_url_token,
    add_ts, last_modify_ts ...
)
```

**特点分析**：
- 知乎的「点赞」命名为 `voteup_count`（不是 `liked_count`）
- 知乎的内容分为 `answer`（回答）、`article`（文章）、`zvideo`（视频回答）三种类型
- `created_time` 是 **字符串类型**（`"1735689600"`）而非 BigInteger，SQL 查询需要 CAST
- 是唯一一个没有 `ip_location` 的内容表（知乎内容发布不带 IP 属地）

### 3.7 贴吧帖子表 `tieba_note`

```sql
CREATE TABLE tieba_note (
    id                      INTEGER PRIMARY KEY,
    note_id                VARCHAR(644) INDEX,    -- 帖子ID
    title                   TEXT,                  -- 帖子标题
    desc                    TEXT,                  -- 帖子正文
    note_url                TEXT,                  -- 帖子URL
    publish_time            VARCHAR(255) INDEX,    -- 发布时间（**字符串格式**）←─ 特殊！
    user_link               TEXT,
    user_nickname           TEXT,
    user_avatar            TEXT,
    tieba_name              TEXT,                  -- 所属贴吧名
    tieba_id                VARCHAR(255),
    tieba_link              TEXT,
    total_replay_num        INTEGER DEFAULT 0,   -- 总回复数 ←───── 贴吧「评论」叫 replay
    total_replay_page       INTEGER DEFAULT 0,
    ip_location             TEXT     DEFAULT '',
    source_keyword         TEXT    DEFAULT '',
    add_ts, last_modify_ts ...
)
```

**特点分析**：
- 贴吧的「评论」命名为 `total_replay_num`（不是 `comment_count`）
- `publish_time` 是**字符串格式**，与微博相同
- 特有的 `tieba_name` 字段——贴吧是**话题社区**而非个人发布，「吧名」就是话题标签

---

## 四、各平台评论表 Schema 逐表解析

### 4.1 横向对比：7 张评论表的字段差异

```
字段名              B站      微博     抖音     快手     小红书   知乎      贴吧
─────────────────────────────────────────────────────────────────────────
comment_id          ✅       ✅      ✅      ✅       ✅       ✅       ✅
user_id             ✅       ✅      ✅      ✅       ✅       ✅       ✅
nickname            ✅       ✅      ✅      ✅       ✅       ✅       ✅
avatar              ✅       ✅      ✅      ✅       ✅       ✅       ✅
content             ✅       ✅      ✅      ✅       ✅       ✅       ✅
create_time         ✅       ✅      ✅      ✅       ✅       ✅       ✅  ← 时间字段
ip_location         ❌       ✅      ✅      ❌       ✅       ✅       ✅  ← 地理字段
like_count          ✅       ❌      ❌      ❌       ✅       ✅       ❌
comment_like_count  ❌       ✅      ❌      ❌       ❌       ❌       ❌
sub_comment_count   ✅       ✅      ✅      ✅       ✅       ❌       ✅
parent_comment_id   ✅       ❌      ✅      ❌       ✅       ❌       ✅
pictures            ❌       ❌      ✅      ❌       ✅       ❌       ❌
note_id/video_id    ✅(video_id) ✅(note_id) ✅(aweme_id) ✅(video_id) ✅(note_id) ✅(content_id) ✅(note_id)  ← 外键字段
```

### 4.2 B站评论表 `bilibili_video_comment`

```sql
CREATE TABLE bilibili_video_comment (
    id                  INTEGER PRIMARY KEY,
    comment_id          BIGINT  INDEX,
    video_id            BIGINT  INDEX,         -- 关联到 bilibili_video.video_id
    user_id             VARCHAR(255),
    nickname            TEXT,
    sex                 TEXT,                  -- B站独有的性别字段
    sign                TEXT,                  -- 用户签名
    avatar              TEXT,
    content             TEXT,                  -- 评论正文
    create_time         BIGINT,               -- 发布时间（Unix 秒）
    sub_comment_count   TEXT,                  -- 子评论数
    parent_comment_id   VARCHAR(255),         -- 父评论ID（楼中楼）
    like_count         TEXT     DEFAULT '0', -- 评论获赞数
    add_ts, last_modify_ts ...
)
```

### 4.3 微博评论表 `weibo_note_comment`

```sql
CREATE TABLE weibo_note_comment (
    id                  INTEGER PRIMARY KEY,
    comment_id          BIGINT  INDEX,
    note_id             BIGINT  INDEX,         -- 关联到 weibo_note.note_id
    user_id             VARCHAR(255),
    nickname            TEXT,
    avatar              TEXT,
    gender              TEXT,
    profile_url         TEXT,
    ip_location         TEXT     DEFAULT '',   -- IP属地
    content             TEXT,                  -- 评论正文
    create_time         BIGINT,               -- 发布时间（Unix 秒）
    create_date_time    VARCHAR(255) INDEX,   -- 可读时间格式 ←─ 微博独有
    comment_like_count  TEXT,                  -- 评论获赞数 ←─ 与B站 like_count 不同名
    sub_comment_count   TEXT,
    parent_comment_id   VARCHAR(255),
    add_ts, last_modify_ts ...
)
```

### 4.4 抖音评论表 `douyin_aweme_comment`

```sql
CREATE TABLE douyin_aweme_comment (
    id                  INTEGER PRIMARY KEY,
    comment_id          BIGINT  INDEX,
    aweme_id            BIGINT  INDEX,         -- 关联到 douyin_aweme.aweme_id
    user_id             VARCHAR(255),
    nickname            TEXT,
    avatar              TEXT,
    ip_location         TEXT,
    content             TEXT,
    create_time         BIGINT,               -- 发布时间（Unix **毫秒**）←─ 与内容表一致
    sub_comment_count   TEXT,
    parent_comment_id   VARCHAR(255),
    like_count         TEXT     DEFAULT '0',
    pictures           TEXT     DEFAULT '',   -- 评论附带图片（抖音独有）
    add_ts, last_modify_ts ...
)
```

### 4.5 知乎评论表 `zhihu_comment`

```sql
CREATE TABLE zhihu_comment (
    id                  INTEGER PRIMARY KEY,
    comment_id          VARCHAR(64) INDEX,
    parent_comment_id   VARCHAR(64),
    content             TEXT,                  -- 评论正文
    publish_time        VARCHAR(32) INDEX,  -- 发布时间（Unix 秒字符串）
    ip_location         TEXT,                  -- IP属地
    sub_comment_count   INTEGER DEFAULT 0,  -- 子评论数（Integer 而非 Text！）
    like_count         INTEGER DEFAULT 0,   -- 点赞数（Integer 而非 Text！）
    dislike_count       INTEGER DEFAULT 0,  -- 点踩数（知乎独有）
    content_id          VARCHAR(64) INDEX,  -- 关联到 zhihu_content.content_id
    content_type        TEXT,                  -- 内容类型
    user_id, user_link, user_nickname, user_avatar ...
)
```

**特点**：知乎评论的 `like_count`/`dislike_count`/`sub_comment_count` 是**Integer 类型**（其他平台都是 Text），这是唯一一处类型一致的字段。

---

## 五、用户/创作者表 Schema

### 5.1 横向对比

```
字段名           B站_upinfo  微博_creator  抖音_creator  快手_creator  小红书_creator  知乎_creator  贴吧_creator
─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
user_id            ✅(BigInt)  ✅(VARCHAR)  ✅(VARCHAR)  ✅(VARCHAR)  ✅(VARCHAR)  ✅(VARCHAR)  ✅(VARCHAR)
nickname           ✅          ✅            ✅            ✅            ✅            ✅            ✅(name)
avatar             ✅          ✅            ✅            ✅            ✅            ✅            ✅(avatar)
gender             ✅          ✅            ✅            ✅            ✅            ✅            ✅
ip_location        ❌          ✅            ✅            ✅            ✅            ✅            ✅
follows/fans        ✅(总数)    ✅(总数)      ✅(总数)      ✅(总数)      ✅(总数)      ✅(follows/fans)  ✅(follows/fans)
tag_list           ❌          ✅(标签)      ❌            ❌            ❌            ❌            ❌
total_fans         ✅          ❌            ❌            ❌            ❌            ❌            ❌
total_liked        ✅          ❌            ❌            ❌            ❌            ❌            ❌
user_rank          ✅(等级)    ❌            ❌            ❌            ❌            ❌            ❌
is_official         ✅(认证)    ❌            ❌            ❌            ❌            ❌            ❌
desc/signature      ❌          ✅(desc)      ✅(desc)      ✅(desc)      ✅(desc)      ❌            ✅(nickname)
interaction         ❌          ❌            ✅            ✅            ✅            ❌            ❌
videos_count       ❌          ❌            ✅            ❌            ❌            ❌            ❌
anwser_count       ❌          ❌            ❌            ❌            ❌            ✅            ❌
article_count      ❌          ❌            ❌            ❌            ❌            ✅            ❌
get_voteup_count   ❌          ❌            ❌            ❌            ❌            ✅            ❌
registration_dur   ❌          ❌            ❌            ❌            ❌            ❌            ✅
```

---

## 六、MindSpider 扩展表（话题发现层）

### 6.1 `daily_news` — 每日热点新闻表

```sql
CREATE TABLE daily_news (
    id              INTEGER PRIMARY KEY AUTO_INCREMENT,
    news_id         VARCHAR(128) NOT NULL,        -- 新闻唯一ID
    source_platform VARCHAR(32)   NOT NULL,        -- 来源平台：weibo|zhihu|bilibili|douyin...
    title           VARCHAR(500)  NOT NULL,       -- 新闻标题（主要搜索字段）
    url             VARCHAR(512)  DEFAULT NULL,   -- 新闻链接
    description     TEXT,                          -- 描述/摘要
    extra_info      TEXT,                          -- 额外信息（JSON格式）
    crawl_date      DATE         NOT NULL,         -- 爬取日期 ←───── 核心分区键
    rank_position   INTEGER       DEFAULT NULL,   -- 在热榜中的排名 ←── 排名即热度！
    add_ts          BIGINT        NOT NULL,
    last_modify_ts  BIGINT        NOT NULL,

    -- 索引
    UNIQUE KEY idx_daily_news_unique (news_id, source_platform, crawl_date),
    KEY idx_daily_news_date (crawl_date),          -- 按日期分区查询
    KEY idx_daily_news_platform (source_platform), -- 按平台过滤
    KEY idx_daily_news_rank (rank_position)        -- 按排名查询 Top-N
)
```

**预测价值**：`rank_position` 是热榜排名（1 = 最热），连续追踪同一 `news_id` 的 `rank_position` 变化即为该话题的「舆情轨迹」。

### 6.2 `daily_topics` — 每日话题表

```sql
CREATE TABLE daily_topics (
    id                  INTEGER PRIMARY KEY AUTO_INCREMENT,
    topic_id            VARCHAR(64)  NOT NULL,   -- 话题唯一ID
    topic_name          VARCHAR(255) NOT NULL,   -- 话题名称
    topic_description   TEXT,                     -- 话题描述（LLM生成）
    keywords            TEXT,                     -- 话题关键词（JSON数组）
    extract_date        DATE       NOT NULL,     -- 提取日期 ←───── 核心分区键
    relevance_score     FLOAT      DEFAULT NULL, -- 相关性得分 ←───── 预测核心指标！
    news_count         INTEGER    DEFAULT 0,    -- 关联新闻数量
    processing_status  VARCHAR(16) DEFAULT 'pending', -- pending|processing|completed|failed
    add_ts, last_modify_ts ...

    -- 索引
    UNIQUE KEY idx_daily_topics_unique (topic_id, extract_date),
    KEY idx_daily_topics_date (extract_date),
    KEY idx_daily_topics_status (processing_status),
    KEY idx_daily_topics_score (relevance_score),  -- 按分数排序查询 Top 话题
    INDEX idx_topic_date_status (extract_date, processing_status)  -- 复合索引
)
```

### 6.3 `topic_news_relation` — 话题新闻关联表

```sql
CREATE TABLE topic_news_relation (
    id              INTEGER PRIMARY KEY AUTO_INCREMENT,
    topic_id        VARCHAR(64)  NOT NULL,   -- 外键 → daily_topics.topic_id
    news_id         VARCHAR(128) NOT NULL,   -- 外键 → daily_news.news_id
    relation_score  FLOAT        DEFAULT NULL,  -- 关联度得分
    extract_date    DATE         NOT NULL,
    add_ts          BIGINT       NOT NULL,

    FOREIGN KEY (topic_id) REFERENCES daily_topics(topic_id) ON DELETE CASCADE,
    FOREIGN KEY (news_id)  REFERENCES daily_news(news_id)   ON DELETE CASCADE
)
```

### 6.4 `crawling_tasks` — 爬取任务表

```sql
CREATE TABLE crawling_tasks (
    id              INTEGER PRIMARY KEY AUTO_INCREMENT,
    task_id         VARCHAR(64)  NOT NULL UNIQUE,
    topic_id        VARCHAR(64)  NOT NULL,   -- 外键 → daily_topics.topic_id
    platform        VARCHAR(32)  NOT NULL,   -- 目标平台
    search_keywords TEXT         NOT NULL,   -- 搜索关键词（JSON数组）
    task_status     VARCHAR(16) DEFAULT 'pending',  -- pending|running|completed|failed|paused
    start_time      BIGINT,                  -- 任务开始时间
    end_time        BIGINT,                  -- 任务结束时间
    total_crawled   INTEGER DEFAULT 0,       -- 已爬取总数
    success_count  INTEGER DEFAULT 0,      -- 成功数
    error_count    INTEGER DEFAULT 0,       -- 错误数
    error_message  TEXT,
    config_params   TEXT,                    -- 爬取配置参数（JSON）
    scheduled_date  DATE        NOT NULL,   -- 计划执行日期
    add_ts, last_modify_ts ...
)
```

---

## 七、Schema 异构性分析：为什么每个平台都不同

### 7.1 字段命名异构的根源

每个平台的 Schema 直接对应平台 API 的响应字段，而非统一抽象：

| 平台 | 点赞字段 | 评论字段 | 分享字段 | 内容ID |
|---|---|---|---|---|
| B站 | `liked_count` | `video_comment` | `video_share_count` | `video_id` |
| 微博 | `liked_count` | `comments_count` | `shared_count` | `note_id` |
| 抖音 | `liked_count` | `comment_count` | `share_count` | `aweme_id` |
| 快手 | `liked_count` | **（无）** | **（无）** | `video_id` |
| 小红书 | `liked_count` | `comment_count` | `share_count` | `note_id` |
| 知乎 | `voteup_count` | `comment_count` | **（无）** | `content_id` |
| 贴吧 | **（无）** | `total_replay_num` | **（无）** | `note_id` |

### 7.2 内容表缺失字段清单

| 平台 | 缺失的通用字段 |
|---|---|
| 快手 | `comment_count`, `share_count`, `collected_count` |
| 知乎 | `share_count`, `collected_count`, `ip_location` |
| 贴吧 | `liked_count`, `share_count`, `collected_count`, `video_url` |
| 微博内容表 | 无 `title` 字段（正文在 `content` 中） |
| 知乎内容表 | 无 `ip_location` |

---

## 八、统一抽象层设计：`_extract_engagement` 如何抹平差异

`InsightEngine/tools/search.py` 中的 `_extract_engagement()` 方法是整个 Schema 异构性的**解决方案**：

```python
# InsightEngine/tools/search.py — line 118

def _extract_engagement(self, row: Dict[str, Any]) -> Dict[str, int]:
    """从数据行中提取并统一互动指标"""
    engagement = {}
    mapping = {
        # 点赞字段：多平台别名 → 统一键 likes
        'likes': [
            'liked_count',      # B站/微博/抖音/快手/小红书
            'like_count',       # B站评论/知乎评论
            'voteup_count',     # 知乎内容
            'comment_like_count' # 微博评论
        ],

        # 评论数字段：多平台别名 → 统一键 comments
        'comments': [
            'video_comment',     # B站视频
            'comments_count',   # 微博
            'comment_count',    # 抖音/小红书/知乎
            'total_replay_num' # 贴吧
        ],

        # 分享数字段
        'shares': [
            'video_share_count',  # B站
            'shared_count',       # 微博
            'share_count'          # 抖音/小红书
        ],

        # 播放/阅读数字段
        'views': [
            'video_play_count',  # B站
            'viewd_count'        # 快手
        ],

        # 收藏数字段
        'favorites': [
            'video_favorite_count',  # B站
            'collected_count'         # 抖音/小红书
        ],

        # 投币数字段（B站独有）
        'coins': ['video_coin_count'],

        # 弹幕数字段（B站独有）
        'danmaku': ['video_danmaku'],
    }

    for key, potential_cols in mapping.items():
        for col in potential_cols:
            if col in row and row[col] is not None:
                try:
                    engagement[key] = int(row[col])
                except (ValueError, TypeError):
                    engagement[key] = 0
                break  # 找到第一个匹配的列就停止
    return engagement
```

**设计原理**：
- **别名映射**：每个统一键对应多个可能的列名，按优先级尝试，第一个有效值胜出
- **类型安全**：所有值都 `int()` 转换，失败则默认为 0，避免 SQL 中 NULL 导致的问题
- **向后兼容**：新平台只需在 `mapping` 中添加新别名，无需修改业务逻辑

---

## 九、时间字段异构问题与解决方案

### 9.1 各平台时间格式汇总

| 平台-表 | 时间字段 | 数据类型 | 格式 | SQL 处理 |
|---|---|---|---|---|
| B站-内容 | `create_time` | BigInteger | Unix 秒 | 直接使用 |
| B站-评论 | `create_time` | BigInteger | Unix 秒 | 直接使用 |
| 微博-内容 | `create_time` | BigInteger | Unix 秒 | 直接使用 |
| 微博-内容 | `create_date_time` | VARCHAR(255) | `"2025-08-22 14:30:00"` | 字符串索引 |
| 微博-评论 | `create_date_time` | VARCHAR(255) | 同上 | 字符串索引 |
| 抖音-内容 | `create_time` | BigInteger | Unix **毫秒** | `÷ 1000` |
| 抖音-评论 | `create_time` | BigInteger | Unix **毫秒** | `÷ 1000` |
| 快手-内容 | `create_time` | BigInteger | Unix **毫秒** | `÷ 1000` |
| 小红书-内容 | `time` | BigInteger | Unix **毫秒** | `÷ 1000` |
| 小红书-评论 | `create_time` | BigInteger | Unix **毫秒** | `÷ 1000` |
| 知乎-内容 | `created_time` | VARCHAR(32) | `"1735689600"` | CAST to BigInt |
| 知乎-评论 | `publish_time` | VARCHAR(32) | 同上 | CAST to BigInt |
| 贴吧-内容 | `publish_time` | VARCHAR(255) | `"2025-08-22 14:30:00"` | 字符串索引 |

### 9.2 统一时间解析工具

```python
# InsightEngine/tools/search.py — line 97

@staticmethod
def _to_datetime(ts: Any) -> Optional[datetime]:
    if not ts: return None
    try:
        if isinstance(ts, datetime): return ts
        if isinstance(ts, date): return datetime.combine(ts, datetime.min.time())

        # 处理数值型时间戳
        if isinstance(ts, (int, float)) or str(ts).isdigit():
            val = float(ts)
            # 关键判断：毫秒 vs 秒（毫秒时间戳 > 1万亿，即 > 2001年）
            return datetime.fromtimestamp(
                val / 1000 if val > 1_000_000_000_000 else val
            )

        # 处理字符串格式
        if isinstance(ts, str):
            return datetime.fromisoformat(ts.split('+')[0].strip())

    except (ValueError, TypeError):
        return None
```

**关键判断逻辑**：如果数值 > 1,000,000,000,000，则判定为**毫秒级时间戳**（抖音/小红书/快手），否则为秒级（B站/微博）。

---

## 十、索引设计分析

### 10.1 内容表索引策略

| 表 | 主键索引 | 唯一索引 | 普通索引 | 缺失索引 |
|---|---|---|---|---|
| `bilibili_video` | `id` | `video_id` | `user_id`, `create_time` | `source_keyword` ⚠️ |
| `douyin_aweme` | `id` | `aweme_id` | `create_time` | `source_keyword` ⚠️ |
| `kuaishou_video` | `id` | `video_id` | `create_time` | `source_keyword` ⚠️ |
| `weibo_note` | `id` | `note_id` | `create_time`, `create_date_time` | `source_keyword` ⚠️ |
| `xhs_note` | `id` | `note_id` | `time` | `source_keyword` ⚠️ |
| `zhihu_content` | `id` | — | `content_id` | `source_keyword` ⚠️ |
| `tieba_note` | `id` | — | `note_id`, `publish_time` | `source_keyword` ⚠️ |

**重要缺陷**：除了 B站和微博外，其他平台的内容表**都没有** `source_keyword` 的索引，导致 `search_topic_globally` 在这些表上做 LIKE 查询时必须全表扫描。

### 10.2 评论表索引策略

| 表 | 主键索引 | 唯一索引 | 普通索引 |
|---|---|---|---|
| `bilibili_video_comment` | `id` | — | `comment_id`, `video_id` |
| `douyin_aweme_comment` | `id` | — | `comment_id`, `aweme_id` |
| `kuaishou_video_comment` | `id` | — | `comment_id`, `video_id` |
| `weibo_note_comment` | `id` | — | `comment_id`, `note_id`, `create_date_time` |
| `xhs_note_comment` | `id` | — | `comment_id`, `note_id` |
| `zhihu_comment` | `id` | — | `comment_id`, `content_id`, `publish_time` |
| `tieba_comment` | `id` | — | `comment_id`, `note_id` |

### 10.3 MindSpider 扩展表索引（设计良好）

```sql
-- daily_news: 按日期分区 + 平台过滤 + 排名排序，三维查询都有索引
KEY idx_daily_news_date (crawl_date)
KEY idx_daily_news_platform (source_platform)
KEY idx_daily_news_rank (rank_position)

-- daily_topics: 分数排序 + 状态过滤的复合索引
KEY idx_daily_topics_score (relevance_score)
KEY idx_daily_topics_status (processing_status)
INDEX idx_topic_date_status (extract_date, processing_status)

-- crawling_tasks: 三维查询都有索引
KEY idx_crawling_tasks_topic (topic_id)
KEY idx_crawling_tasks_platform (platform)
KEY idx_crawling_tasks_status (task_status)
KEY idx_crawling_tasks_date (scheduled_date)
INDEX idx_task_topic_platform (topic_id, platform, task_status)  -- 复合最左前缀
```

---

## 十一、Schema 扩展字段（MindSpider 增强）

所有 7 个内容表都通过 ALTER TABLE 添加了 MindSpider 扩展字段：

```sql
-- 所有内容表统一添加以下两列（ALTER TABLE）
ALTER TABLE `{platform}_content`
    ADD COLUMN `topic_id`         VARCHAR(64) DEFAULT NULL COMMENT '关联的话题ID',
    ADD COLUMN `crawling_task_id` VARCHAR(64) DEFAULT NULL COMMENT '关联的爬取任务ID';
```

这使得：
- 任何内容都可以追溯到它是由哪个话题触发的爬取任务产生的
- 支持从 `daily_topics.topic_id` → `crawling_tasks` → 平台内容表的完整链路追踪

---

## 十二、新项目 Schema 设计建议

### 12.1 当前设计的优点

1. **平台原生性保留完好**：不丢失任何平台特有字段
2. **统一抽象层有效**：`_extract_engagement()` 成功抹平了 7 个平台的字段差异
3. **MindSpider 扩展优雅**：通过 ALTER TABLE 添加 topic_id，不破坏原 MediaCrawler 设计
4. **索引设计合理**：MindSpider 扩展表索引覆盖了三维查询需求

### 12.2 当前设计的缺陷

| 缺陷 | 影响 | 建议修复 |
|---|---|---|
| 参与度字段全为 TEXT 类型 | SQL 中必须 CAST，性能差 | 新建项目建议用 DECIMAL(20,0) |
| `source_keyword` 无索引 | LIKE 查询必须全表扫描 | 添加索引或改用全文索引 |
| 快手/贴吧缺失多个参与度字段 | 跨平台横向对比不公平 | 业务层用 NULL 填充并降权 |
| 知乎时间字段为 VARCHAR | 时间范围查询效率低 | 改为 BigInteger |
| 无统一的 user_id 体系 | 跨平台用户追踪无法实现 | 考虑统一用户指纹（设备指纹/手机号） |
| 缺少 `updated_time` 的主动更新 | 内容变更（如编辑）无法追踪 | 增加更新触发器或定时任务 |

### 12.3 推荐的新项目 Schema 设计

**方案 A：保留平台异构，在查询层统一（推荐，参考 BettaFish 原设计）**

```
各平台原始表（保持原生字段）
        ↓
MediaCrawlerDB._extract_engagement()  ←─ 字段归一化
        ↓
统一查询结果：QueryResult(platform, content_type, title_or_content,
                          engagement={likes/comments/shares/views/favorites/coins/danmaku},
                          publish_time, hotness_score, ...)
        ↓
Insight Agent 节点流水线
```

**方案 B：强制统一 Schema（适合数据仓库场景）**

```
平台原始数据 → ETL Pipeline → 统一宽表
```

统一宽表 Schema 设计建议：

```sql
CREATE TABLE unified_content (
    id                  BIGINT PRIMARY KEY AUTO_INCREMENT,
    platform            VARCHAR(32)  NOT NULL,   -- 平台标识
    platform_content_id VARCHAR(128) NOT NULL,    -- 平台原生ID
    content_type        VARCHAR(16)  NOT NULL,    -- video/note/article/comment
    title               TEXT,
    body                TEXT,                       -- 统一正文字段
    author_id           VARCHAR(128),
    author_nickname     TEXT,
    publish_time        DATETIME(3)  NOT NULL,   -- 统一毫秒精度时间
    -- 统一参与度字段（DECIMAL，避免精度丢失）
    likes               DECIMAL(20,0) DEFAULT 0,
    comments             DECIMAL(20,0) DEFAULT 0,
    shares              DECIMAL(20,0) DEFAULT 0,
    views               DECIMAL(20,0) DEFAULT 0,
    favorites           DECIMAL(20,0) DEFAULT 0,
    coins               DECIMAL(20,0) DEFAULT 0,
    danmaku             DECIMAL(20,0) DEFAULT 0,
    -- 地理信息
    ip_location         VARCHAR(128),
    -- 平台特有字段（JSON 保留）
    platform_extra      JSON,
    -- 业务字段
    source_keyword      VARCHAR(255) DEFAULT '',
    hotness_score       DECIMAL(20,2) DEFAULT 0,
    topic_id            VARCHAR(64),
    add_ts              BIGINT,
    last_modify_ts      BIGINT,

    UNIQUE KEY (platform, platform_content_id),
    KEY (platform, publish_time),
    KEY (hotness_score DESC),
    KEY (source_keyword)
)
```

---

*文档基于 BettaFish (GPL-2.0 License) 源码生成，供技术分析与学习参考。*
