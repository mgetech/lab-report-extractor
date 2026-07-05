using Npgsql;

namespace LabReportExtractor.Api.Data;

/// <summary>
/// Builds the Postgres connection string from <c>ConnectionStrings:DefaultConnection</c> if set,
/// else composes it from the individual <c>POSTGRES_*</c> environment variables (see CLAUDE.md).
/// </summary>
public static class PostgresConnectionStringBuilder
{
    public static string Build(IConfiguration configuration)
    {
        var configured = configuration.GetConnectionString("DefaultConnection");
        if (!string.IsNullOrWhiteSpace(configured))
        {
            return configured;
        }

        return new NpgsqlConnectionStringBuilder
        {
            Host = configuration["POSTGRES_HOST"] ?? "localhost",
            Port = int.Parse(configuration["POSTGRES_PORT"] ?? "5432"),
            Database = configuration["POSTGRES_DB"] ?? "medreports",
            Username = configuration["POSTGRES_USER"] ?? "postgres",
            Password = configuration["POSTGRES_PASSWORD"] ?? "postgres",
        }.ConnectionString;
    }
}