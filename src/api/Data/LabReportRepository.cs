using LabReportExtractor.Api.Models;
using Microsoft.EntityFrameworkCore;

namespace LabReportExtractor.Api.Data;

/// <summary>
/// EF Core access to lab reports. Patient, results and diagnoses are
/// owned by <see cref="LabReport"/>, so they're saved and loaded with it automatically.
/// </summary>
public sealed class LabReportRepository(LabReportDbContext context)
{
    /// <summary>Inserts a lab report with its results/diagnoses. Returns the new row's id.</summary>
    public async Task<long> InsertAsync(LabReport report, CancellationToken cancellationToken = default)
    {
        context.LabReports.Add(report);
        await context.SaveChangesAsync(cancellationToken);
        return report.Id!.Value;
    }

    /// <summary>Reads a lab report with its results/diagnoses by id, or <see langword="null"/> if it doesn't exist.</summary>
    public Task<LabReport?> GetByIdAsync(long id, CancellationToken cancellationToken = default) =>
        context.LabReports.FirstOrDefaultAsync(r => r.Id == id, cancellationToken);
}