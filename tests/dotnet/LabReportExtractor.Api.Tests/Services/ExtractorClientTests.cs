using System.Net;
using System.Net.Http.Json;
using System.Text;
using LabReportExtractor.Api.Models;
using LabReportExtractor.Api.Services;
using Microsoft.AspNetCore.Http;

namespace LabReportExtractor.Api.Tests.Services;

/// <summary>
/// Exercises <see cref="ExtractorClient"/> against a stubbed <see cref="HttpMessageHandler"/> —
/// mirrors the Python-side convention of mocking the Azure clients, proving this client is
/// testable without a live extractor.
/// </summary>
public class ExtractorClientTests
{
    [Fact]
    public async Task ExtractAsync_ReturnsReport_OnSuccess()
    {
        var report = SampleReport();
        var handler = new StubHttpMessageHandler((request, _) =>
        {
            Assert.Equal(HttpMethod.Post, request.Method);
            Assert.Equal("/extract", request.RequestUri!.PathAndQuery);
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = JsonContent.Create(report) };
        });

        var client = new ExtractorClient(CreateHttpClient(handler));
        var file = CreateFormFile("report.pdf", "application/pdf", "%PDF-1.4 fake content");

        var result = await client.ExtractAsync(file);

        Assert.Equal(report.SourceFile, result.SourceFile);
        Assert.Equal(report.Patient.Name, result.Patient.Name);
    }

    [Fact]
    public async Task ExtractAsync_ThrowsWithDetail_WhenExtractorReturnsError()
    {
        var handler = new StubHttpMessageHandler((_, _) => new HttpResponseMessage(HttpStatusCode.UnprocessableEntity)
        {
            Content = JsonContent.Create(new { detail = "Unreadable document." }),
        });

        var client = new ExtractorClient(CreateHttpClient(handler));
        var file = CreateFormFile("bad.pdf", "application/pdf", "not a real pdf");

        var exception = await Assert.ThrowsAsync<ExtractorRequestException>(() => client.ExtractAsync(file));

        Assert.Equal(422, exception.StatusCode);
        Assert.Equal("Unreadable document.", exception.Message);
    }

    [Fact]
    public async Task PingAsync_Throws_WhenExtractorUnhealthy()
    {
        var handler = new StubHttpMessageHandler((_, _) => new HttpResponseMessage(HttpStatusCode.ServiceUnavailable));

        var client = new ExtractorClient(CreateHttpClient(handler));

        await Assert.ThrowsAsync<ExtractorRequestException>(() => client.PingAsync());
    }

    [Fact]
    public async Task PingAsync_Succeeds_WhenExtractorHealthy()
    {
        var handler = new StubHttpMessageHandler((_, _) => new HttpResponseMessage(HttpStatusCode.OK));

        var client = new ExtractorClient(CreateHttpClient(handler));

        await client.PingAsync();
    }

    private static HttpClient CreateHttpClient(HttpMessageHandler handler) =>
        new(handler) { BaseAddress = new Uri("http://extractor.test") };

    private static IFormFile CreateFormFile(string fileName, string contentType, string content)
    {
        var stream = new MemoryStream(Encoding.UTF8.GetBytes(content));
        return new FormFile(stream, 0, stream.Length, "file", fileName)
        {
            Headers = new HeaderDictionary(),
            ContentType = contentType,
        };
    }

    private static LabReport SampleReport() => new()
    {
        SourceFile = "report.pdf",
        ExtractionModel = "gpt-5-mini",
        ExtractedAt = DateTimeOffset.UtcNow,
        NeedsReview = false,
        Patient = new Patient { PatientId = "P-1", Name = "Test Patient" },
    };

    private sealed class StubHttpMessageHandler(Func<HttpRequestMessage, CancellationToken, HttpResponseMessage> responder)
        : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken) =>
            Task.FromResult(responder(request, cancellationToken));
    }
}