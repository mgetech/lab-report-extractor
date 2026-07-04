using System.Text.Json;
using Dapper;
using LabReportExtractor.Api.Models;
using Npgsql;

namespace LabReportExtractor.Api.Data;

/// <summary>
/// Dapper-based access to the <c>lab_reports</c> / <c>results</c> tables — the only writer of the
/// system of record (see CLAUDE.md ownership rules: Postgres has exactly one writer, this API).
/// </summary>
public sealed class LabReportRepository(NpgsqlDataSource dataSource)
{
    private const string InsertLabReportSql = """
        INSERT INTO lab_reports
            (patient_id, patient_name, patient_dob, patient_sex,
             report_date, collection_date, ordering_physician, lab_name,
             source_file, extraction_model, extracted_at, needs_review, diagnoses)
        VALUES
            (@PatientId, @PatientName, @PatientDob, @PatientSex,
             @ReportDate, @CollectionDate, @OrderingPhysician, @LabName,
             @SourceFile, @ExtractionModel, @ExtractedAt, @NeedsReview, @Diagnoses::jsonb)
        RETURNING id
        """;

    private const string InsertResultSql = """
        INSERT INTO results
            (lab_report_id, analyte, value, unit, ref_range_raw, ref_low, ref_high,
             printed_flag, computed_flag, confidence, needs_review)
        VALUES
            (@LabReportId, @Analyte, @Value, @Unit, @RefRangeRaw, @RefLow, @RefHigh,
             @PrintedFlag, @ComputedFlag, @Confidence, @NeedsReview)
        """;

    private const string SelectLabReportByIdSql = """
        SELECT id, patient_id, patient_name, patient_dob, patient_sex,
               report_date, collection_date, ordering_physician, lab_name,
               source_file, extraction_model, extracted_at, needs_review, diagnoses
        FROM lab_reports
        WHERE id = @Id;

        SELECT id, lab_report_id, analyte, value, unit, ref_range_raw, ref_low, ref_high,
               printed_flag, computed_flag, confidence, needs_review
        FROM results
        WHERE lab_report_id = @Id
        ORDER BY id;
        """;

    /// <summary>Inserts a lab report and its result rows in one transaction. Returns the new row's id.</summary>
    public async Task<long> InsertAsync(LabReport report, CancellationToken cancellationToken = default)
    {
        await using var connection = await dataSource.OpenConnectionAsync(cancellationToken);
        await using var transaction = await connection.BeginTransactionAsync(cancellationToken);

        var labReportId = await connection.ExecuteScalarAsync<long>(new CommandDefinition(
            InsertLabReportSql,
            new
            {
                report.Patient.PatientId,
                PatientName = report.Patient.Name,
                PatientDob = report.Patient.Dob,
                PatientSex = report.Patient.Sex?.ToCode(),
                report.ReportDate,
                report.CollectionDate,
                report.OrderingPhysician,
                report.LabName,
                report.SourceFile,
                report.ExtractionModel,
                report.ExtractedAt,
                report.NeedsReview,
                Diagnoses = JsonSerializer.Serialize(report.Diagnoses),
            },
            transaction,
            cancellationToken: cancellationToken));

        if (report.Results.Count > 0)
        {
            var resultParams = report.Results.Select(result => new
            {
                LabReportId = labReportId,
                result.Analyte,
                result.Value,
                result.Unit,
                result.RefRangeRaw,
                result.RefLow,
                result.RefHigh,
                PrintedFlag = result.PrintedFlag?.ToCode(),
                ComputedFlag = result.ComputedFlag?.ToCode(),
                result.Confidence,
                result.NeedsReview,
            });

            await connection.ExecuteAsync(new CommandDefinition(
                InsertResultSql, resultParams, transaction, cancellationToken: cancellationToken));
        }

        await transaction.CommitAsync(cancellationToken);
        return labReportId;
    }

    /// <summary>Reads a lab report with its results by id, or <see langword="null"/> if it doesn't exist.</summary>
    public async Task<LabReport?> GetByIdAsync(long id, CancellationToken cancellationToken = default)
    {
        await using var connection = await dataSource.OpenConnectionAsync(cancellationToken);
        await using var multi = await connection.QueryMultipleAsync(
            new CommandDefinition(SelectLabReportByIdSql, new { Id = id }, cancellationToken: cancellationToken));

        var header = await multi.ReadSingleOrDefaultAsync<LabReportRow>();
        if (header is null)
        {
            return null;
        }

        var resultRows = (await multi.ReadAsync<ResultRow>()).ToList();
        return MapToLabReport(header, resultRows);
    }

    private static LabReport MapToLabReport(LabReportRow header, IReadOnlyList<ResultRow> resultRows) =>
        new()
        {
            Id = header.Id,
            SourceFile = header.SourceFile,
            ExtractionModel = header.ExtractionModel,
            ExtractedAt = header.ExtractedAt,
            ReportDate = header.ReportDate,
            CollectionDate = header.CollectionDate,
            OrderingPhysician = header.OrderingPhysician,
            LabName = header.LabName,
            NeedsReview = header.NeedsReview,
            Patient = new Patient
            {
                PatientId = header.PatientId,
                Name = header.PatientName,
                Dob = header.PatientDob,
                Sex = header.PatientSex is null ? null : SexCode.ParseCode(header.PatientSex),
            },
            Results = resultRows.Select(row => new Result
            {
                Analyte = row.Analyte,
                Value = row.Value,
                Unit = row.Unit,
                RefRangeRaw = row.RefRangeRaw,
                RefLow = row.RefLow,
                RefHigh = row.RefHigh,
                PrintedFlag = row.PrintedFlag is null ? null : FlagCode.ParseCode(row.PrintedFlag),
                ComputedFlag = row.ComputedFlag is null ? null : FlagCode.ParseCode(row.ComputedFlag),
                Confidence = row.Confidence,
                NeedsReview = row.NeedsReview,
            }).ToList(),
            Diagnoses = JsonSerializer.Deserialize<List<Diagnosis>>(header.Diagnoses) ?? [],
        };

    private sealed record LabReportRow(
        long Id,
        string PatientId,
        string PatientName,
        DateOnly? PatientDob,
        string? PatientSex,
        DateOnly? ReportDate,
        DateOnly? CollectionDate,
        string? OrderingPhysician,
        string? LabName,
        string SourceFile,
        string ExtractionModel,
        DateTimeOffset ExtractedAt,
        bool NeedsReview,
        string Diagnoses);

    private sealed record ResultRow(
        long Id,
        long LabReportId,
        string Analyte,
        string Value,
        string? Unit,
        string? RefRangeRaw,
        double? RefLow,
        double? RefHigh,
        string? PrintedFlag,
        string? ComputedFlag,
        double Confidence,
        bool NeedsReview);
}