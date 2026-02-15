# Unity → Substance 3D Painter Bridge (BIRP/Standard向け)

※AI生成を使用してこのプロジェクトは作成されています。  
このパッケージは、Unity Editor拡張から以下を自動化します。

- 対象GameObject（Renderer/SkinnedMeshRenderer）を指定
- Material(主にStandard)からテクスチャ抽出（BaseColor/Normal/AO/Emission/MetallicSmoothness 等）
- FBX Exporter（com.unity.formats.fbx）でFBX自動生成
  - SkinnedをBakeして静的メッシュ化（任意）
  - ルート原点化（Off / Pivot / BoundsCenter）＋回転/スケールリセット（任意）
- ローカルのSubstance 3D Painterを Remote Scripting で操作
  - 既存 .spp をコピーして使用、または新規作成
  - テクスチャをProject Resourcesへインポート
  - Fill Layerを生成し、命名規則（*_BaseColor / *_Normal / *_MetallicSmoothness / *_Roughness / *_AO / *_Emission…）で自動挿し
  - Export preset をヒント文字列で自動検出してエクスポート

## 前提
- Windows想定（bat/py）
- Unity 2021.3.4f1 または Unity 6
- Package Managerで「FBX Exporter（com.unity.formats.fbx）」を導入済み
- Painter は `--enable-remote-scripting` で起動（バッチで自動起動します）
- Python 3.x（`py -3` が使える環境）

## 配置
このzipの `Unity` フォルダを、あなたのUnityプロジェクト直下にマージしてください。

- `Assets/Editor/*.cs` : Editor拡張
- `Tools/SubstancePainter/*` : 実行用バッチ/ランナー

## 使い方（最短）
1. Unityで `Tools > Substance 3D Painter > Substance 3D Painter Exporter` を開く
2. Target Object にエクスポートしたいGameObjectを指定
3. Output .spp Path と Export Folder を指定
   - 既存.sppをコピーして使うなら Existing .spp to Copy を指定
   - 新規作成なら Mesh Path は空でもOK（FBXを自動生成）
4. FBX Export Options で
   - Skinned Bake
   - Root Origin Mode（Off/Pivot/BoundsCenter）
   - Rotation/Scale reset
   を必要に応じて設定
5. `Build Job & Run` を押す

## 注意
- Fill Layerの自動挿しはPainterのバージョン/シェーダでキー名が変わることがあります。
  Painterログに "Fill parameters keys:" が出るので、必要に応じて Tools/Substance3DPainter/run_painter_job.py のマッチ条件を調整してください。
