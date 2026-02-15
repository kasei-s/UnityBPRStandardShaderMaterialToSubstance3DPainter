// Assets/Editor/SubstancePainterObjectExporterWindow.cs
#nullable enable
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using UnityEditor;
using UnityEngine;

public class SubstancePainterObjectExporterWindow : EditorWindow
{
    [Header("Target")]
    GameObject? targetObject;

    [Header("Painter / Tools")]
    string toolsFolder = "Tools/Substance3DPainter";
    string jobRunnerBat = "run_painter_job.bat";
    //string painterExePath = @"C:\Program Files\Adobe\Adobe Substance 3D Painter\Adobe Substance 3D Painter.exe";
    string painterExePath = @"D:\Program Files (x86)\Steam\steamapps\common\Substance 3D Painter 2025\Adobe Substance 3D Painter.exe";
    string painterAppLogPathOverride = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData) + "\\Adobe\\Adobe Substance 3D Painter\\log.txt"; // optional; auto-detected if empty

    [Header("Project")]
    string existingSppToCopy = "";
    string meshPathForNewProject = "";
    string templateSptPath = "";
    string outputSppPath = "";
    string exportFolder = "";

    [Header("TextureSet Naming")]
    bool useMaterialNameAsTextureSet = true;
    string textureSetNameOverride = "Main";

    [Header("Options")]
    bool useUDIM = false;
    bool autoDetectExportPreset = true;
    string exportPresetHint = "Unity";
    string exportPresetExact = "";

    [Header("FBX Export Options")]
    bool bakeSkinnedToStaticMesh = true;
    FbxMeshExporter.RootOriginMode originMode = FbxMeshExporter.RootOriginMode.Pivot;
    bool resetRotationScaleOnOrigin = true;

    [Header("Export Maps")]
    bool exportBaseColor = true;
    bool exportNormal = true;
    bool exportAO = true;
    bool exportEmission = true;
    bool exportHeight = true;
    bool generateMetallic = true;
    bool generateRoughnessFromSmoothness = true;

    Vector2 scroll;

    [MenuItem("Tools/Substance 3D Painter/Object → Substance 3D Painter Exporter")]
    public static void Open()
    {
        var w = GetWindow<SubstancePainterObjectExporterWindow>("Object→Substance3DPainter");
        w.minSize = new Vector2(680, 760);
    }

    void OnSelectionChange()
    {
        if (Selection.activeGameObject != null) targetObject = Selection.activeGameObject;
        Repaint();
    }

    void OnGUI()
    {
        scroll = EditorGUILayout.BeginScrollView(scroll);

        EditorGUILayout.LabelField("Unity Object → Substance 3D Painter Export", EditorStyles.boldLabel);

        using (new EditorGUILayout.VerticalScope("box"))
        {
            targetObject = (GameObject?)EditorGUILayout.ObjectField("Target Object", targetObject, typeof(GameObject), true);
            if (GUILayout.Button("Use Selected GameObject"))
            {
                if (Selection.activeGameObject != null) targetObject = Selection.activeGameObject;
            }
        }

        using (new EditorGUILayout.VerticalScope("box"))
        {
            EditorGUILayout.LabelField("Painter / Tools", EditorStyles.boldLabel);
            painterExePath = EditorGUILayout.TextField("Painter EXE", painterExePath);
            painterAppLogPathOverride = EditorGUILayout.TextField("Painter App Log (optional)", painterAppLogPathOverride);
            toolsFolder = EditorGUILayout.TextField("Tools Folder", toolsFolder);
            jobRunnerBat = EditorGUILayout.TextField("Runner BAT", jobRunnerBat);
        }

        using (new EditorGUILayout.VerticalScope("box"))
        {
            EditorGUILayout.LabelField("Painter Project", EditorStyles.boldLabel);
            existingSppToCopy = EditorGUILayout.TextField("Existing .spp to Copy (optional)", existingSppToCopy);
            meshPathForNewProject = EditorGUILayout.TextField("Mesh Path for New Project (optional)", meshPathForNewProject);
            templateSptPath = EditorGUILayout.TextField("Template .spt (optional)", templateSptPath);
            outputSppPath = EditorGUILayout.TextField("Output .spp Path", outputSppPath);
            exportFolder = EditorGUILayout.TextField("Export Folder", exportFolder);
        }

        using (new EditorGUILayout.VerticalScope("box"))
        {
            EditorGUILayout.LabelField("TextureSet Naming", EditorStyles.boldLabel);
            useMaterialNameAsTextureSet = EditorGUILayout.ToggleLeft("Use Material Name as TextureSet", useMaterialNameAsTextureSet);
            using (new EditorGUI.DisabledScope(useMaterialNameAsTextureSet))
            {
                textureSetNameOverride = EditorGUILayout.TextField("TextureSet Name", textureSetNameOverride);
            }
        }

        using (new EditorGUILayout.VerticalScope("box"))
        {
            EditorGUILayout.LabelField("Options", EditorStyles.boldLabel);
            useUDIM = EditorGUILayout.ToggleLeft("Use UDIM (flag)", useUDIM);

            autoDetectExportPreset = EditorGUILayout.ToggleLeft("Auto Detect Export Preset", autoDetectExportPreset);
            using (new EditorGUI.DisabledScope(!autoDetectExportPreset))
                exportPresetHint = EditorGUILayout.TextField("Preset Hint", exportPresetHint);

            using (new EditorGUI.DisabledScope(autoDetectExportPreset))
                exportPresetExact = EditorGUILayout.TextField("Preset Exact Name", exportPresetExact);
        }

        using (new EditorGUILayout.VerticalScope("box"))
        {
            EditorGUILayout.LabelField("FBX Export Options", EditorStyles.boldLabel);
            bakeSkinnedToStaticMesh = EditorGUILayout.ToggleLeft("Skinned → BakeMesh and export as static mesh", bakeSkinnedToStaticMesh);
            originMode = (FbxMeshExporter.RootOriginMode)EditorGUILayout.EnumPopup("Root Origin Mode", originMode);

            using (new EditorGUI.DisabledScope(originMode == FbxMeshExporter.RootOriginMode.Off))
            {
                resetRotationScaleOnOrigin = EditorGUILayout.ToggleLeft("Also reset Rotation/Scale (rot=identity, scale=1)", resetRotationScaleOnOrigin);
            }
        }

        using (new EditorGUILayout.VerticalScope("box"))
        {
            EditorGUILayout.LabelField("Maps", EditorStyles.boldLabel);
            exportBaseColor = EditorGUILayout.ToggleLeft("Export BaseColor (_MainTex)", exportBaseColor);
            exportNormal = EditorGUILayout.ToggleLeft("Export Normal (_BumpMap)", exportNormal);
            exportAO = EditorGUILayout.ToggleLeft("Export AO (_OcclusionMap)", exportAO);
            exportEmission = EditorGUILayout.ToggleLeft("Export Emission (_EmissionMap)", exportEmission);
            exportHeight = EditorGUILayout.ToggleLeft("Export Height (_ParallaxMap)", exportHeight);
            generateMetallic = EditorGUILayout.ToggleLeft("Generate Metallic (MetallicSmoothness.R)", generateMetallic);
            generateRoughnessFromSmoothness = EditorGUILayout.ToggleLeft("Generate Roughness = 1 - Smoothness(Alpha)", generateRoughnessFromSmoothness);
        }

        EditorGUILayout.Space(12);
        using (new EditorGUI.DisabledScope(targetObject == null))
        {
            if (GUILayout.Button("Build Job & Run", GUILayout.Height(38)))
            {
                try
                {
                    BuildJobAndRun();
                    EditorUtility.DisplayDialog("Object→Painter", "Started. Check console / Painter logs.", "OK");
                }
                catch (Exception ex)
                {
                    UnityEngine.Debug.LogException(ex);
                    EditorUtility.DisplayDialog("Error", ex.Message, "OK");
                }
            }
        }

        EditorGUILayout.EndScrollView();
    }

    void BuildJobAndRun()
    {
        if (targetObject == null) throw new Exception("Target Object is not set.");
        if (string.IsNullOrWhiteSpace(outputSppPath)) throw new Exception("Output .spp Path is required.");
        if (string.IsNullOrWhiteSpace(exportFolder)) throw new Exception("Export Folder is required.");
        if (!File.Exists(painterExePath)) throw new Exception($"Painter EXE not found: {painterExePath}");

        Directory.CreateDirectory(Path.GetDirectoryName(outputSppPath) ?? ".");
        Directory.CreateDirectory(exportFolder);

        var materials = CollectMaterials(targetObject);
        if (materials.Count == 0) throw new Exception("No materials found on target object (Renderer).");

        var workRoot = Path.Combine(Path.GetDirectoryName(outputSppPath) ?? ".", "_SP_Work");
        Directory.CreateDirectory(workRoot);

        var useExisting = !string.IsNullOrWhiteSpace(existingSppToCopy);
        if (!useExisting)
        {
            if (string.IsNullOrWhiteSpace(meshPathForNewProject))
            {
                var meshOutDir = Path.Combine(workRoot, "_Mesh");
                Directory.CreateDirectory(meshOutDir);

                var baseName = SafeFileName(targetObject.name);
                var fbxPath = Path.Combine(meshOutDir, $"{baseName}.fbx");

                meshPathForNewProject = FbxMeshExporter.ExportGameObjectToFbx(
                    targetObject,
                    fbxPath,
                    bakeSkinnedToStaticMesh,
                    originMode,
                    resetRotationScaleOnOrigin
                );

                UnityEngine.Debug.Log($"[SP] Auto exported FBX: {meshPathForNewProject}");
            }

            if (!File.Exists(meshPathForNewProject))
                throw new Exception("Mesh path for new project is required (FBX auto export failed or path invalid).");
        }

        var texSets = new List<JobTextureSet>();
        foreach (var mat in materials)
        {
            if (mat == null) continue;

            var texSetName = useMaterialNameAsTextureSet ? SanitizeName(mat.name) : SanitizeName(textureSetNameOverride);
            var outDir = Path.Combine(workRoot, texSetName);
            Directory.CreateDirectory(outDir);

            var exported = ExportFromStandardMaterial(mat, texSetName, outDir);
            if (exported.Count == 0) continue;

            var entries = exported.Select(kv => new JobTextureEntry(kv.Key, kv.Value)).ToList();
            texSets.Add(new JobTextureSet { name = texSetName, textures = entries });
        }

        if (texSets.Count == 0)
            throw new Exception("No textures exported. Are your materials using Standard shader textures?");

        var job = new JobData
        {
            painterExePath = painterExePath,
            painterAppLogPath = ResolvePainterAppLogPath(painterAppLogPathOverride),
            existingProjectToCopy = existingSppToCopy,
            meshPath = meshPathForNewProject,
            templateSptPath = templateSptPath,
            outputProjectPath = outputSppPath,
            exportFolder = exportFolder,
            useUDIM = useUDIM,
            autoDetectExportPreset = autoDetectExportPreset,
            exportPresetNameHint = exportPresetHint,
            exportPresetExactName = exportPresetExact,
            textureSets = texSets
        };

        var jobJsonPath = Path.Combine(workRoot, "job.json");
        File.WriteAllText(jobJsonPath, JsonUtility.ToJson(job, true), Encoding.UTF8);

        var batPath = Path.GetFullPath(Path.Combine(Application.dataPath, "..", toolsFolder, jobRunnerBat));
        if (!File.Exists(batPath)) throw new Exception($"BAT not found: {batPath}");

        var psi = new ProcessStartInfo
        {
            FileName = batPath,
            Arguments = $"\"{jobJsonPath}\"",
            UseShellExecute = true,
            WorkingDirectory = Path.GetDirectoryName(batPath)
        };
        Process.Start(psi);
    }


    static string ResolvePainterAppLogPath(string overridePath)
    {
        // If user provided a path, prefer it.
        if (!string.IsNullOrWhiteSpace(overridePath) && File.Exists(overridePath))
            return overridePath;

        // Auto-detect latest Painter application log.
        // Typical names: Log_Substance 3D Painter_*.txt
        // Typical locations (varies by install):
        //   %LOCALAPPDATA%\Adobe\Adobe Substance 3D Painter\log(s)\...
        //   %APPDATA%\Adobe\Adobe Substance 3D Painter\log(s)\...
        //   %USERPROFILE%\Documents\...
        var candidates = new List<string>();

        void TryScan(string root, int maxDepth)
        {
            if (string.IsNullOrWhiteSpace(root) || !Directory.Exists(root)) return;
            try
            {
                var stack = new Stack<(string path, int depth)>();
                stack.Push((root, 0));
                while (stack.Count > 0)
                {
                    var (p, d) = stack.Pop();
                    if (d > maxDepth) continue;

                    try
                    {
                        foreach (var f in Directory.EnumerateFiles(p, "Log_Substance 3D Painter_*.txt", SearchOption.TopDirectoryOnly))
                            candidates.Add(f);
                    }
                    catch { }

                    if (d == maxDepth) continue;

                    try
                    {
                        foreach (var dir in Directory.EnumerateDirectories(p))
                            stack.Push((dir, d + 1));
                    }
                    catch { }
                }
            }
            catch { }
        }

        string localApp = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        string appData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
        string userProfile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);

        // Shallow scans to avoid heavy recursion in big folders.
        TryScan(Path.Combine(localApp, "Adobe", "Adobe Substance 3D Painter", "log"), 4);
        TryScan(Path.Combine(localApp, "Adobe", "Adobe Substance 3D Painter", "logs"), 4);
        TryScan(Path.Combine(localApp, "Adobe", "Substance 3D Painter", "log"), 4);
        TryScan(Path.Combine(localApp, "Adobe", "Substance 3D Painter", "logs"), 4);

        TryScan(Path.Combine(appData, "Adobe", "Adobe Substance 3D Painter", "log"), 4);
        TryScan(Path.Combine(appData, "Adobe", "Adobe Substance 3D Painter", "logs"), 4);
        TryScan(Path.Combine(appData, "Adobe", "Substance 3D Painter", "log"), 4);
        TryScan(Path.Combine(appData, "Adobe", "Substance 3D Painter", "logs"), 4);

        // As a last resort, scan Documents shallowly (users sometimes copy logs here)
        TryScan(Path.Combine(userProfile, "Documents"), 3);

        if (candidates.Count == 0) return "";

        // Pick most recently written log.
        candidates.Sort((a, b) => File.GetLastWriteTimeUtc(b).CompareTo(File.GetLastWriteTimeUtc(a)));
        return candidates[0];
    }

    static List<Material> CollectMaterials(GameObject go)
    {
        var list = new List<Material>();
        foreach (var r in go.GetComponentsInChildren<Renderer>(true))
        {
            if (r.sharedMaterials == null) continue;
            foreach (var m in r.sharedMaterials)
                if (m != null && !list.Contains(m)) list.Add(m);
        }
        return list;
    }

    const string MAIN_TEX = "_MainTex";
    const string BUMP_MAP = "_BumpMap";
    const string OCCLUSION = "_OcclusionMap";
    const string METALLIC_GLOSS = "_MetallicGlossMap";
    const string EMISSION = "_EmissionMap";
    const string PARALLAX_MAP = "_ParallaxMap";

    Dictionary<string, string> ExportFromStandardMaterial(Material mat, string texSetName, string outDir)
    {
        var map = new Dictionary<string, string>();

        Texture2D? albedo = GetTex(mat, MAIN_TEX);
        Texture2D? normal = GetTex(mat, BUMP_MAP);
        Texture2D? ao = GetTex(mat, OCCLUSION);
        Texture2D? metSm = GetTex(mat, METALLIC_GLOSS);
        Texture2D? emis = GetTex(mat, EMISSION);
        Texture2D? heightTex = GetTex(mat, PARALLAX_MAP);

        // デバッグ: 各テクスチャの取得状況をログ出力
        UnityEngine.Debug.Log($"[SP] Texture check: albedo={albedo != null}, normal={normal != null}, ao={ao != null}, metSm={metSm != null}, emis={emis != null}, heightTex={heightTex != null} (HasProperty={mat.HasProperty(PARALLAX_MAP)})");

        if (exportBaseColor && albedo) map["BaseColor"] = BakeToPng(albedo, Path.Combine(outDir, $"{texSetName}_BaseColor.png"));
        if (exportNormal && normal) map["Normal"] = BakeNormalToPng(normal, Path.Combine(outDir, $"{texSetName}_Normal.png"));
        if (exportAO && ao) map["AO"] = BakeToPng(ao, Path.Combine(outDir, $"{texSetName}_AO.png"));
        if (exportEmission && emis) map["Emission"] = BakeToPng(emis, Path.Combine(outDir, $"{texSetName}_Emission.png"));
        if (exportHeight)
        {
            if (heightTex)
            {
                map["Height"] = BakeToPng(heightTex, Path.Combine(outDir, $"{texSetName}_Height.png"));
                UnityEngine.Debug.Log($"[SP] Height texture exported from _ParallaxMap: {heightTex.name} ({heightTex.width}x{heightTex.height})");
            }
            else
            {
                // _ParallaxMap テクスチャが無い場合、
                // Substance Painter の Height チャンネル用に中間グレー（0.5 = ニュートラル）を生成する。
                // _Parallax はスケール値（通常 0.02）なので、テクスチャが無い場合は変位なし。
                float heightVal = 0.5f; // ニュートラル（変位なし）
                var heightSolid = CreateSolidTexture(256, 256, heightVal);
                var path = Path.Combine(outDir, $"{texSetName}_Height.png");
                File.WriteAllBytes(path, heightSolid.EncodeToPNG());
                map["Height"] = path;
                DestroyImmediateSafe(heightSolid);
                UnityEngine.Debug.Log($"[SP] Generated neutral Height texture (0.5 gray) — no _ParallaxMap found");
            }
        }

        if (metSm)
        {
            // MetallicSmoothness 合成テクスチャはデバッグ用に保存するが、
            // Painter の job には含めない（分解した Metallic / Roughness を使用する）
            BakeToPng(metSm, Path.Combine(outDir, $"{texSetName}_MetallicSmoothness.png"));

            var readable = GetReadableCopy(metSm);

            if (generateMetallic)
            {
                // MetallicGlossMap の R チャンネル = Metallic
                var metallic = ExtractChannel(readable, Channel.R);
                var path = Path.Combine(outDir, $"{texSetName}_Metallic.png");
                File.WriteAllBytes(path, metallic.EncodeToPNG());
                map["Metallic"] = path;
                DestroyImmediateSafe(metallic);
            }

            if (generateRoughnessFromSmoothness)
            {
                // MetallicGlossMap の A チャンネル = Smoothness → 反転して Roughness
                var smooth = ExtractChannel(readable, Channel.A);
                var rough = InvertGrayscale(smooth);
                var path = Path.Combine(outDir, $"{texSetName}_Roughness.png");
                File.WriteAllBytes(path, rough.EncodeToPNG());
                map["Roughness"] = path;
                DestroyImmediateSafe(smooth);
                DestroyImmediateSafe(rough);
            }

            DestroyImmediateSafe(readable);
        }
        else
        {
            // MetallicGlossMap テクスチャが無い場合、
            // マテリアルのスカラー値から単色テクスチャを生成する
            if (generateMetallic && mat.HasProperty("_Metallic"))
            {
                float metallicVal = mat.GetFloat("_Metallic");
                var metallic = CreateSolidTexture(256, 256, metallicVal);
                var path = Path.Combine(outDir, $"{texSetName}_Metallic.png");
                File.WriteAllBytes(path, metallic.EncodeToPNG());
                map["Metallic"] = path;
                DestroyImmediateSafe(metallic);
                UnityEngine.Debug.Log($"[SP] Generated Metallic from scalar value: {metallicVal}");
            }

            if (generateRoughnessFromSmoothness && mat.HasProperty("_Glossiness"))
            {
                float smoothness = mat.GetFloat("_Glossiness");
                float roughness = 1f - smoothness;
                var rough = CreateSolidTexture(256, 256, roughness);
                var path = Path.Combine(outDir, $"{texSetName}_Roughness.png");
                File.WriteAllBytes(path, rough.EncodeToPNG());
                map["Roughness"] = path;
                DestroyImmediateSafe(rough);
                UnityEngine.Debug.Log($"[SP] Generated Roughness from scalar Smoothness={smoothness} → Roughness={roughness}");
            }
        }

        return map;
    }

    static Texture2D? GetTex(Material mat, string prop)
        => mat.HasProperty(prop) ? mat.GetTexture(prop) as Texture2D : null;

    enum Channel { R, G, B, A }

    static string BakeToPng(Texture2D tex, string outPath)
    {
        var readable = GetReadableCopy(tex);
        File.WriteAllBytes(outPath, readable.EncodeToPNG());
        DestroyImmediateSafe(readable);
        return outPath;
    }

    // ===== Normal export fix (Unity DXT5nm-like swizzle -> RGB normal) =====
    static string BakeNormalToPng(Texture2D tex, string outPath)
    {
        var readable = GetReadableCopy(tex);

        bool looksLikeDxt5nm = LooksLikeUnityDxt5nm(readable);

        Texture2D outTex = looksLikeDxt5nm
            ? ReconstructFromUnityDxt5nm(readable)
            : NormalizeBlueFromRGB(readable);

        File.WriteAllBytes(outPath, outTex.EncodeToPNG());

        DestroyImmediateSafe(readable);
        DestroyImmediateSafe(outTex);

        return outPath;
    }

    static bool LooksLikeUnityDxt5nm(Texture2D t)
    {
        var px = t.GetPixels32();
        if (px == null || px.Length == 0) return false;

        int step = Mathf.Max(1, px.Length / 2048);
        int rMin = 255, rMax = 0, aMin = 255, aMax = 0;

        for (int i = 0; i < px.Length; i += step)
        {
            var p = px[i];
            if (p.r < rMin) rMin = p.r;
            if (p.r > rMax) rMax = p.r;
            if (p.a < aMin) aMin = p.a;
            if (p.a > aMax) aMax = p.a;
        }

        // Rがほぼ固定(≈255)で、Aがそこそこ動く → UnityのDXT5nm系に該当しやすい
        return (rMax - rMin) <= 2 && rMin >= 250 && (aMax - aMin) > 8;
    }

    static Texture2D ReconstructFromUnityDxt5nm(Texture2D src)
    {
        var px = src.GetPixels32();

        for (int i = 0; i < px.Length; i++)
        {
            float x = (px[i].a / 255f) * 2f - 1f; // X = Alpha
            float y = (px[i].g / 255f) * 2f - 1f; // Y = Green

            // Painter側で陰影が反転する場合は有効化してください
            // y = -y;

            float z2 = 1f - x * x - y * y;
            float z = Mathf.Sqrt(Mathf.Max(0f, z2));

            byte r = (byte)Mathf.RoundToInt((x * 0.5f + 0.5f) * 255f);
            byte g = (byte)Mathf.RoundToInt((y * 0.5f + 0.5f) * 255f);
            byte b = (byte)Mathf.RoundToInt((z * 0.5f + 0.5f) * 255f);

            px[i] = new Color32(r, g, b, 255);
        }

        var dst = new Texture2D(src.width, src.height, TextureFormat.RGBA32, false, true);
        dst.SetPixels32(px);
        dst.Apply(false, false);
        return dst;
    }

    static Texture2D NormalizeBlueFromRGB(Texture2D src)
    {
        // 既にRGB normalっぽい時に、青(Z)が壊れている場合の保険（不要なら outTex=readable でもOK）
        var px = src.GetPixels32();

        for (int i = 0; i < px.Length; i++)
        {
            float x = (px[i].r / 255f) * 2f - 1f;
            float y = (px[i].g / 255f) * 2f - 1f;

            float z = Mathf.Sqrt(Mathf.Max(0f, 1f - x * x - y * y));
            byte b = (byte)Mathf.RoundToInt((z * 0.5f + 0.5f) * 255f);

            px[i] = new Color32(px[i].r, px[i].g, b, 255);
        }

        var dst = new Texture2D(src.width, src.height, TextureFormat.RGBA32, false, true);
        dst.SetPixels32(px);
        dst.Apply(false, false);
        return dst;
    }


    static Texture2D GetReadableCopy(Texture2D src)
    {
        var rt = RenderTexture.GetTemporary(src.width, src.height, 0, RenderTextureFormat.ARGB32, RenderTextureReadWrite.Linear);
        Graphics.Blit(src, rt);

        var prev = RenderTexture.active;
        RenderTexture.active = rt;

        var dst = new Texture2D(src.width, src.height, TextureFormat.RGBA32, false, true);
        dst.ReadPixels(new Rect(0, 0, src.width, src.height), 0, 0);
        dst.Apply(false, false);

        RenderTexture.active = prev;
        RenderTexture.ReleaseTemporary(rt);
        return dst;
    }

    static Texture2D ExtractChannel(Texture2D src, Channel ch)
    {
        var px = src.GetPixels32();
        var outPx = new Color32[px.Length];
        for (int i = 0; i < px.Length; i++)
        {
            byte v = ch switch
            {
                Channel.R => px[i].r,
                Channel.G => px[i].g,
                Channel.B => px[i].b,
                Channel.A => px[i].a,
                _ => px[i].r
            };
            outPx[i] = new Color32(v, v, v, 255);
        }
        var dst = new Texture2D(src.width, src.height, TextureFormat.RGBA32, false, true);
        dst.SetPixels32(outPx);
        dst.Apply(false, false);
        return dst;
    }

    static Texture2D InvertGrayscale(Texture2D gray)
    {
        var px = gray.GetPixels32();
        for (int i = 0; i < px.Length; i++)
        {
            byte v = px[i].r;
            byte inv = (byte)(255 - v);
            px[i] = new Color32(inv, inv, inv, 255);
        }
        var dst = new Texture2D(gray.width, gray.height, TextureFormat.RGBA32, false, true);
        dst.SetPixels32(px);
        dst.Apply(false, false);
        return dst;
    }

    /// <summary>
    /// 指定した値（0〜1）で塗りつぶした単色グレースケールテクスチャを生成する。
    /// MetallicGlossMap が無い場合にスカラー値から Metallic / Roughness を作るために使用。
    /// </summary>
    static Texture2D CreateSolidTexture(int width, int height, float value01)
    {
        byte v = (byte)Mathf.RoundToInt(Mathf.Clamp01(value01) * 255f);
        var tex = new Texture2D(width, height, TextureFormat.RGBA32, false, true);
        var px = new Color32[width * height];
        for (int i = 0; i < px.Length; i++)
            px[i] = new Color32(v, v, v, 255);
        tex.SetPixels32(px);
        tex.Apply(false, false);
        return tex;
    }

    static void DestroyImmediateSafe(UnityEngine.Object? o)
    {
        if (o != null) UnityEngine.Object.DestroyImmediate(o);
    }

    static string SafeFileName(string s)
    {
        foreach (var c in Path.GetInvalidFileNameChars())
            s = s.Replace(c, '_');
        return string.IsNullOrWhiteSpace(s) ? "Mesh" : s;
    }

    static string SanitizeName(string s) => string.IsNullOrWhiteSpace(s) ? "TexSet" : s.Replace(' ', '_');

    [Serializable]
    class JobData
    {
        public string painterExePath = "";
        public string painterAppLogPath = "";
        public string existingProjectToCopy = "";
        public string meshPath = "";
        public string templateSptPath = "";
        public string outputProjectPath = "";
        public string exportFolder = "";

        public bool useUDIM;
        public bool autoDetectExportPreset;
        public string exportPresetNameHint = "Unity";
        public string exportPresetExactName = "";

        public List<JobTextureSet> textureSets = new();
    }

    [Serializable]
    class JobTextureSet
    {
        public string name = "";
        public List<JobTextureEntry> textures = new();
    }

    [Serializable]
    class JobTextureEntry
    {
        public string key = "";
        public string path = "";
        public JobTextureEntry() { }
        public JobTextureEntry(string k, string p) { key = k; path = p; }
    }
}
