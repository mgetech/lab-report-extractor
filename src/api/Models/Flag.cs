using System.Text.Json.Serialization;

namespace LabReportExtractor.Api.Models;

/// <summary>Printed or recomputed normal/abnormal flag, mirroring <c>schema.Flag</c> on the Python side.</summary>
[JsonConverter(typeof(JsonStringEnumConverter<Flag>))]
public enum Flag
{
    [JsonStringEnumMemberName("N")]
    Normal,

    [JsonStringEnumMemberName("H")]
    High,

    [JsonStringEnumMemberName("L")]
    Low,

    [JsonStringEnumMemberName("HH")]
    CriticalHigh,

    [JsonStringEnumMemberName("LL")]
    CriticalLow,
}

/// <summary>Short-code conversions for <see cref="Flag"/>, matching the Python <c>StrEnum</c> values — used by the data layer, where the column stores the code directly rather than the enum member name.</summary>
public static class FlagCode
{
    public static string ToCode(this Flag flag) => flag switch
    {
        Flag.Normal => "N",
        Flag.High => "H",
        Flag.Low => "L",
        Flag.CriticalHigh => "HH",
        Flag.CriticalLow => "LL",
        _ => throw new ArgumentOutOfRangeException(nameof(flag), flag, "Unknown flag."),
    };

    public static Flag ParseCode(string code) => code switch
    {
        "N" => Flag.Normal,
        "H" => Flag.High,
        "L" => Flag.Low,
        "HH" => Flag.CriticalHigh,
        "LL" => Flag.CriticalLow,
        _ => throw new ArgumentOutOfRangeException(nameof(code), code, "Unknown flag code."),
    };
}