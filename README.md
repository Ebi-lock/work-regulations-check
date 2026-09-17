# work-regulations-check

日本の労務・人事向け [Claude Code](https://claude.com/claude-code) プラグイン集です。

社内規程を、**e-Gov法令検索と厚生労働省の資料から取得した原文を根拠に**点検します。
条番号や割増率を記憶で書かないこと、施行日を必ず確認することを設計の中心に置いています。

## 収録プラグイン

| プラグイン | 内容 |
|---|---|
| [work-regulations-check](./plugins/work-regulations-check) | 就業規則を労働基準法などに照らして点検し、必須記載事項の漏れ・違法やリスクのある条項・法改正への未対応・形式面の不整合をレポートにまとめる |

## インストール

Claude Code で次を実行します。

```
/plugin marketplace add Ebi-lock/work-regulations-check
/plugin install work-regulations-check@work-regulations-check
```

あとは就業規則のファイルを指して話しかけるだけです。

```
就業規則.pdf をチェックして
この規程、法改正に対応できてる？
```

## 免責

**出力は法的助言ではありません。** 社会保険労務士・弁護士に相談する前の一次スクリーニングです。
就業規則の作成・変更の代行は社会保険労務士の業務に関わります。
実際の改定にあたっては必ず専門家の確認を受けてください。

詳しくは各プラグインのREADMEに記載しています。出力内容に起因する損害について作者は責任を負いません。

## 出典

- [e-Gov法令検索](https://laws.e-gov.go.jp/)（デジタル庁）
- [厚生労働省 モデル就業規則](https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/roudoukijun/zigyonushi/model/index.html)
- [厚生労働省 国会提出法案](https://www.mhlw.go.jp/topics/bukyoku/soumu/houritu/index.html)

## ライセンス

MIT
