using System.Text.Json.Serialization;

namespace LabReportExtractor.Api.Models;

/// <summary>Patient sex, mirroring <c>schema.Sex</c> on the Python side.</summary>
[JsonConverter(typeof(JsonStringEnumConverter<Sex>))]
public enum Sex
{
    [JsonStringEnumMemberName("M")]
    Male,

    [JsonStringEnumMemberName("F")]
    Female,

    [JsonStringEnumMemberName("O")]
    Other,

    [JsonStringEnumMemberName("U")]
    Unknown,
}

/// <summary>Short-code conversions for <see cref="Sex"/>, matching the Python <c>StrEnum</c> values — used by the data layer, where the column stores the code directly rather than the enum member name.</summary>
public static class SexCode
{
    public static string ToCode(this Sex sex) => sex switch
    {
        Sex.Male => "M",
        Sex.Female => "F",
        Sex.Other => "O",
        Sex.Unknown => "U",
        _ => throw new ArgumentOutOfRangeException(nameof(sex), sex, "Unknown sex."),
    };

    public static Sex ParseCode(string code) => code switch
    {
        "M" => Sex.Male,
        "F" => Sex.Female,
        "O" => Sex.Other,
        "U" => Sex.Unknown,
        _ => throw new ArgumentOutOfRangeException(nameof(code), code, "Unknown sex code."),
    };
}