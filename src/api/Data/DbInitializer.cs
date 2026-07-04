using System.Reflection;
using Npgsql;

namespace LabReportExtractor.Api.Data;

/// <summary>
/// Applies <c>schema.sql</c> against Postgres on startup. Idempotent (every statement is
/// <c>CREATE ... IF NOT EXISTS</c>) and non-fatal: if Postgres isn't reachable yet, this logs a
/// warning and returns rather than crashing the process — <c>/health</c> must come up green
/// regardless of DB state; <c>/ready</c> is what actually gates on Postgres being reachable.
/// </summary>
public static class DbInitializer
{
    private const string SchemaResourceName = "LabReportExtractor.Api.Data.schema.sql";

    public static async Task InitializeAsync(
        NpgsqlDataSource dataSource, ILogger logger, CancellationToken cancellationToken = default)
    {
        try
        {
            var schemaSql = await ReadSchemaSqlAsync(cancellationToken);
            await using var connection = await dataSource.OpenConnectionAsync(cancellationToken);
            await using var command = new NpgsqlCommand(schemaSql, connection);
            await command.ExecuteNonQueryAsync(cancellationToken);
            logger.LogInformation("Database schema verified/applied.");
        }
        catch (Exception ex)
        {
            logger.LogWarning(ex, "Could not apply database schema on startup; will retry to reflect this via /ready.");
        }
    }

    private static async Task<string> ReadSchemaSqlAsync(CancellationToken cancellationToken)
    {
        var assembly = Assembly.GetExecutingAssembly();
        await using var stream = assembly.GetManifestResourceStream(SchemaResourceName)
            ?? throw new InvalidOperationException($"Embedded resource '{SchemaResourceName}' not found.");
        using var reader = new StreamReader(stream);
        return await reader.ReadToEndAsync(cancellationToken);
    }
}