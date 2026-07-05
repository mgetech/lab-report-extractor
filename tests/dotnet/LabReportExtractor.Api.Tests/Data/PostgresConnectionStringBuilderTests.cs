using LabReportExtractor.Api.Data;
using Microsoft.Extensions.Configuration;

namespace LabReportExtractor.Api.Tests.Data;

public class PostgresConnectionStringBuilderTests
{
    [Fact]
    public void Build_UsesConfiguredConnectionString_WhenPresent()
    {
        var configuration = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["ConnectionStrings:DefaultConnection"] = "Host=explicit;Database=explicit_db",
            })
            .Build();

        var connectionString = PostgresConnectionStringBuilder.Build(configuration);

        Assert.Equal("Host=explicit;Database=explicit_db", connectionString);
    }

    [Fact]
    public void Build_ComposesFromPostgresEnvVars_WhenNoConnectionStringConfigured()
    {
        var configuration = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["POSTGRES_HOST"] = "db",
                ["POSTGRES_PORT"] = "5432",
                ["POSTGRES_DB"] = "medreports",
                ["POSTGRES_USER"] = "postgres",
                ["POSTGRES_PASSWORD"] = "secret",
            })
            .Build();

        var connectionString = PostgresConnectionStringBuilder.Build(configuration);

        Assert.Contains("Host=db", connectionString);
        Assert.Contains("Port=5432", connectionString);
        Assert.Contains("Database=medreports", connectionString);
        Assert.Contains("Username=postgres", connectionString);
        Assert.Contains("Password=secret", connectionString);
    }

    [Fact]
    public void Build_FallsBackToDefaults_WhenNothingConfigured()
    {
        var configuration = new ConfigurationBuilder().Build();

        var connectionString = PostgresConnectionStringBuilder.Build(configuration);

        Assert.Contains("Host=localhost", connectionString);
        Assert.Contains("Port=5432", connectionString);
        Assert.Contains("Database=medreports", connectionString);
        Assert.Contains("Username=postgres", connectionString);
        Assert.Contains("Password=postgres", connectionString);
    }
}