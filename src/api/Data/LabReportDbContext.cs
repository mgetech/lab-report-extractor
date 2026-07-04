using LabReportExtractor.Api.Models;
using Microsoft.EntityFrameworkCore;

namespace LabReportExtractor.Api.Data;

/// <summary>
/// EF Core context for the system of record. <see cref="LabReport"/> is the only aggregate root —
/// <see cref="Patient"/>, <see cref="Result"/> and <see cref="Diagnosis"/> are owned types, so they
/// always load and save together with their <see cref="LabReport"/> (no explicit <c>.Include()</c>
/// needed).
/// </summary>
public sealed class LabReportDbContext(DbContextOptions<LabReportDbContext> options) : DbContext(options)
{
    public DbSet<LabReport> LabReports => Set<LabReport>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<LabReport>(report =>
        {
            // Patient fields live as columns on lab_reports (a report always carries exactly one
            // patient; no cross-report patient identity resolution in this case study).
            report.OwnsOne(r => r.Patient, patient =>
            {
                // Explicit column name/required: "PatientId" otherwise collides with EF's FK-like
                // naming convention and silently loses its NOT NULL constraint.
                patient.Property(p => p.PatientId).HasColumnName("patient_id").IsRequired();
                patient.Property(p => p.Sex).HasConversion<string>();
            });
            report.Navigation(r => r.Patient).IsRequired();

            // Results get their own table — the one-to-many that drives the review queue.
            report.OwnsMany(r => r.Results, result =>
            {
                result.ToTable("results");
                result.Property(r => r.PrintedFlag).HasConversion<string>();
                result.Property(r => r.ComputedFlag).HasConversion<string>();
            });

            // Diagnoses are a small, schemaless free-text list, never queried on their own —
            // mapped straight to a JSON column, no separate table.
            report.OwnsMany(r => r.Diagnoses, diagnosis => diagnosis.ToJson());
        });
    }
}
