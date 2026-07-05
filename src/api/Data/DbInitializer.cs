namespace LabReportExtractor.Api.Data;

/// <summary>
/// Creates the database schema from the EF Core model on startup via <c>EnsureCreated</c> — no
/// migrations. Idempotent and non-fatal: if Postgres isn't reachable yet, this logs a warning and
/// returns rather than crashing the process — <c>/health</c> must come up green regardless of DB
/// state; <c>/ready</c> is what actually gates on Postgres being reachable.
/// </summary>
public static class DbInitializer
{
    public static async Task InitializeAsync(
        LabReportDbContext context, ILogger logger, CancellationToken cancellationToken = default)
    {
        try
        {
            await context.Database.EnsureCreatedAsync(cancellationToken);
            logger.LogInformation("Database schema verified/applied.");
        }
        catch (Exception ex)
        {
            logger.LogWarning(ex, "Could not apply database schema on startup; will retry to reflect this via /ready.");
        }
    }
}