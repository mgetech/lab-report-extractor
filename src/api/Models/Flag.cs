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