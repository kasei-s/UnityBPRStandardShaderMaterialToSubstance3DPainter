// Assets/Editor/FbxMeshExporter.cs
#nullable enable
using System;
using System.IO;
using System.Reflection;
using UnityEditor;
using UnityEngine;

public static class FbxMeshExporter
{
    public enum RootOriginMode
    {
        Off = 0,
        Pivot = 1,
        BoundsCenter = 2
    }

    public static string ExportGameObjectToFbx(
        GameObject sourceRoot,
        string outputFbxAbsolutePath,
        bool bakeSkinnedMesh,
        RootOriginMode originMode,
        bool resetRotationScale)
    {
        if (sourceRoot == null) throw new ArgumentNullException(nameof(sourceRoot));
        if (string.IsNullOrWhiteSpace(outputFbxAbsolutePath)) throw new ArgumentException("outputFbxAbsolutePath is empty.");

        outputFbxAbsolutePath = Path.GetFullPath(outputFbxAbsolutePath);
        Directory.CreateDirectory(Path.GetDirectoryName(outputFbxAbsolutePath)!);

        var modelExporterType =
            Type.GetType("UnityEditor.Formats.Fbx.Exporter.ModelExporter, Unity.Formats.Fbx.Editor")
            ?? Type.GetType("UnityEditor.Formats.Fbx.Exporter.ModelExporter, Unity.Formats.Fbx.Editor.dll");

        if (modelExporterType == null)
            throw new Exception("FBX Exporter (com.unity.formats.fbx) が見つかりません。Package Manager で FBX Exporter を導入してください。");

        var tempRoot = UnityEngine.Object.Instantiate(sourceRoot);
        tempRoot.name = sourceRoot.name + "_FBXExportTemp";
        tempRoot.hideFlags = HideFlags.HideAndDontSave;
        tempRoot.transform.SetParent(null, true);

        try
        {
            if (bakeSkinnedMesh)
                BakeSkinnedMeshesInPlace(tempRoot);

            if (originMode != RootOriginMode.Off)
                ApplyOriginMode(tempRoot, originMode, resetRotationScale);

            var result = TryExportWithOptions(modelExporterType, tempRoot, outputFbxAbsolutePath, originMode, resetRotationScale)
                      ?? ExportWithoutOptions(modelExporterType, tempRoot, outputFbxAbsolutePath);

            if (string.IsNullOrWhiteSpace(result) || !File.Exists(result))
                throw new Exception("FBX Export failed (result empty or file not found).");

            return result!;
        }
        finally
        {
            UnityEngine.Object.DestroyImmediate(tempRoot);
        }
    }

    static void ApplyOriginMode(GameObject root, RootOriginMode mode, bool resetRotScale)
    {
        var t = root.transform;

        if (mode == RootOriginMode.Pivot)
        {
            t.position = Vector3.zero;
            if (resetRotScale)
            {
                t.rotation = Quaternion.identity;
                t.localScale = Vector3.one;
            }
            return;
        }

        if (mode == RootOriginMode.BoundsCenter)
        {
            if (!TryGetWorldBounds(root, out var b))
            {
                t.position = Vector3.zero;
                if (resetRotScale)
                {
                    t.rotation = Quaternion.identity;
                    t.localScale = Vector3.one;
                }
                return;
            }

            var center = b.center;
            t.position -= center;

            if (resetRotScale)
            {
                t.rotation = Quaternion.identity;
                t.localScale = Vector3.one;
            }
        }
    }

    static bool TryGetWorldBounds(GameObject root, out Bounds bounds)
    {
        var renderers = root.GetComponentsInChildren<Renderer>(true);
        bool has = false;
        bounds = default;

        foreach (var r in renderers)
        {
            if (!r) continue;
            var b = r.bounds;
            if (!has) { bounds = b; has = true; }
            else bounds.Encapsulate(b);
        }
        return has;
    }

    static void BakeSkinnedMeshesInPlace(GameObject root)
    {
        var smrs = root.GetComponentsInChildren<SkinnedMeshRenderer>(true);
        foreach (var smr in smrs)
        {
            if (!smr.sharedMesh) continue;

            var bakedMesh = new Mesh();
            bakedMesh.name = smr.sharedMesh.name + "_Baked";
            smr.BakeMesh(bakedMesh);

            var mf = smr.gameObject.GetComponent<MeshFilter>();
            if (!mf) mf = smr.gameObject.AddComponent<MeshFilter>();
            mf.sharedMesh = bakedMesh;

            var mr = smr.gameObject.GetComponent<MeshRenderer>();
            if (!mr) mr = smr.gameObject.AddComponent<MeshRenderer>();
            mr.sharedMaterials = smr.sharedMaterials;

            UnityEngine.Object.DestroyImmediate(smr);
        }
    }

    static string? TryExportWithOptions(
        Type modelExporterType,
        GameObject exportRoot,
        string outPath,
        RootOriginMode originMode,
        bool resetRotScale)
    {
        var exportOptionsType =
            Type.GetType("UnityEditor.Formats.Fbx.Exporter.ExportModelOptions, Unity.Formats.Fbx.Editor")
            ?? Type.GetType("UnityEditor.Formats.Fbx.Exporter.ExportModelOptions, Unity.Formats.Fbx.Editor.dll");

        if (exportOptionsType == null) return null;

        var m = modelExporterType.GetMethod(
            "ExportObject",
            BindingFlags.Public | BindingFlags.Static,
            binder: null,
            types: new[] { typeof(string), typeof(UnityEngine.Object), exportOptionsType },
            modifiers: null);

        if (m == null) return null;

        var opts = Activator.CreateInstance(exportOptionsType)!;

        SetPropIfExists(opts, "AnimateSkinnedMesh", false);

        if (originMode != RootOriginMode.Off && resetRotScale)
            TrySetEnumProp(opts, "ObjectPosition", new[] { "WorldAbsolute", "Reset", "LocalCentered" });

        var result = m.Invoke(null, new object[] { outPath, exportRoot, opts }) as string;
        return result;
    }

    static string ExportWithoutOptions(Type modelExporterType, GameObject exportRoot, string outPath)
    {
        var m = modelExporterType.GetMethod(
            "ExportObject",
            BindingFlags.Public | BindingFlags.Static,
            binder: null,
            types: new[] { typeof(string), typeof(UnityEngine.Object) },
            modifiers: null);

        if (m == null)
            throw new Exception("ModelExporter.ExportObject(string, Object) が見つかりません。FBX Exporter の版を確認してください。");

        var result = m.Invoke(null, new object[] { outPath, exportRoot }) as string;
        return result ?? "";
    }

    static void SetPropIfExists(object obj, string propName, object value)
    {
        var p = obj.GetType().GetProperty(propName, BindingFlags.Public | BindingFlags.Instance);
        if (p != null && p.CanWrite)
        {
            try { p.SetValue(obj, value); } catch { }
        }
    }

    static bool TrySetEnumProp(object obj, string propName, string[] enumCandidateNames)
    {
        var p = obj.GetType().GetProperty(propName, BindingFlags.Public | BindingFlags.Instance);
        if (p == null || !p.CanWrite) return false;

        var enumType = p.PropertyType;
        if (!enumType.IsEnum) return false;

        foreach (var name in enumCandidateNames)
        {
            try
            {
                var v = Enum.Parse(enumType, name, ignoreCase: true);
                p.SetValue(obj, v);
                return true;
            }
            catch { }
        }
        return false;
    }
}
