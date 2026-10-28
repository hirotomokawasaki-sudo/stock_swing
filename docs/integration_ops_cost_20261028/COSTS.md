# API/AI使用量・費用の把握範囲

2026-10-28に既存5ファイルを私有コピーへ固定し、元byte SHA256/サイズを記録。[レビュー入力](usage_review_inputs.json)は必要フィールドだけを残し、decision IDは同じSHA256へ置換、自由文error/skip_reason・symbol/context内容は除外。原本のCSV形を検査した抽出コードも保存している。認証情報、会話、請求書、OpenClawの他セッションは読んでいない。

## 使用量として観測できた範囲

| データ | 行数・記録tokens | 時間範囲（UTC） | 性質/扱い |
|---|---|---|---|
| token_usage.csv | 240行、入力345,709/出力62,712/計408,421 | 7/13 13:36〜10/27 19:55 | workflow=paper_demo集計。provider usageの出所欄なし。モデル欄は戦略識別子/ルールベース。課金tokensとは認定しない |
| ai_usage.jsonl | 1,939decision、入力372,353/出力44,225/計416,578 | 5/12 02:26〜7/10 13:35 | 全行estimated_rule_based。JSON長由来の旧推定。実LLM呼出数ではない |
| token_usage_backfill.csv | 同じ1,939decision/416,578 | 同上 | JSONとのID・token/model/source一致1,939、相違0。別使用量として加算しない |
| legacy_mixed_schema archive | 1,970行/455,695 | 5/12〜7/31 | 推定1,939行＋runtime31行。31行も現行CSVに完全重複。archiveを加算しない |
| api_latency.csv | 1,399記録（ok1,369/error30） | 6/24 13:25〜10/27 19:55 | account377/bars646/positions376。p50 543.5ms、p95 nearest-rank 2,077.4ms。計測された呼出範囲に限る |

最新ログはJSTで2026-10-28 04:55頃。10/28全日や全APIを網羅するログではない。全体calendarの網羅率/欠落run数は未認定。skip/log件数を独立した有料API呼出へ変換しない。

各token行の非負整数・入力＋出力＝計、aware timestamp、costの有限/非負を検査。5入力内の記録に当該数値/日時異常や完全重複行はなし。ただし別データ間の重複は上記のとおり。archiveは同じ11列でもschemaが異なるため、単一headerのDictReader集計では誤る。3コメント/1headerを除外し、tailのsourceまたはboolean列で旧2schemaを識別。未知形は除外理由を記録し黙って0にしない。

元CSV/JSONから別経路でSQLite SUM/JOINを実行し、行数/各token合計/1,939ID一致/latency1,399行/旧runtime31重複を照合。[独立結果](usage_independent.json)。監査コードは欠損・NaN・不整合・混在schema・自由文除外・重複非加算の10テストで確認。初回はテスト用import path不足で収集失敗、PYTHONPATHを隔離jobへ明示して再実行。初期archive解析も31runtime行の誤分類を検出し、schema境界の受入を追加して確定した。分析の修正であり本番データは変更していない。

## 費用として分かること/分からないこと

- 現行240行とbackfill/旧archiveの`estimated_cost`合計はそれぞれ記録上0.0。**0円/無料/請求ゼロではない**。通貨欄もない。
- 保存した現行paper_demo書込経路は`estimated_cost=0.0`を固定で渡し、モデル欄は集計model_countsの先頭。1workflow集計を特定のLLM使用量やモデル別請求に変換できない。backfillも0.0固定、estimated_rule_basedは旧証拠JSON長/4の推定。
- 現行attach_ai_telemetryにはrule_based_zero/provider_actual/estimatedの区分がある。今回の旧ログをそのままprovider_actualへ昇格しない。**この5入力だけでは実provider使用量・実請求額を確認できない**。他経路に有料LLM呼出が一切ないとの全システム証明でもない。
- latencyのreported retry_countは全行0だが、内部adapter retryや記録外endpointの全HTTP数の証明ではない。1,399を課金request数にしない。
- Massive等のデータ契約、AI API、OpenClawモデル/クラウド、税・通貨/FX、手動作業コスト、実注文手数料/TCAは未集計。実請求/契約明細がないため月額・年額・節約額を推定しない。新価格調査や有料契約は行っていない。

## 残条件（既存P4/S1の費用契約へ）

| 不足 | 担当/取得元 | 次の確認 | 再開条件 |
|---|---|---|---|
| 実支払・通貨・課金期間/契約枠 | 本人、既存provider請求/契約明細 | 2026-10-30 18:00 JSTに有無だけ確認 | 本人提供または既存正規取得経路。ログ0で代用しない |
| 呼出単位のprovider_actualと請求照合 | agent、既存usage_source/request IDを使う最小記録案 | 11/06 18:00 JSTの不足込み一次結論 | 実LLMを研究対象にする場合のみ。新しい計測基盤を先行実装しない |
| 手数料/TCA/税/FX・許容収益減epsilon等 | 本人の条件＋agentの入力表 | 10/30、未充足は11/06にも明記 | 実入力/方針を確認。今回のシステム使用ログ費用と混ぜない |

費用の欠測はP4全体完了の証拠にならない。一方、費用請求の不足を理由に独立して可能な技術確認/探索研究を一律停止する条件にも追加しない。
