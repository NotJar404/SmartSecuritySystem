using System;

namespace WebApp.Models
{
    public class Alert
    {
        public int Id { get; set; }

        public string Title { get; set; }           // Example: "Unauthorized Person"
        public string Description { get; set; }     // Example: "Unknown person detected at main entrance"
        public string Location { get; set; }        // Example: "Front Door", "Back Yard"

        // Use enum for Severity
        public SeverityLevel Severity { get; set; } = SeverityLevel.WARNING;

        // Use enum for Status
        public AlertStatus Status { get; set; } = AlertStatus.Active;

        public DateTime CreatedAt { get; set; } = DateTime.Now;

        // Computed property: minutes since creation
        public int MinutesAgo => (int)(DateTime.Now - CreatedAt).TotalMinutes;

        // Computed property: true if alert is critical
        public bool IsCritical => Severity == SeverityLevel.CRITICAL;

        // Computed property: true if alert is resolved
        public bool IsResolved => Status == AlertStatus.Resolved;
    }

    // Enums for safer values
    public enum SeverityLevel
    {
        WARNING,
        CRITICAL
    }

    public enum AlertStatus
    {
        Active,
        Acknowledged,
        Resolved
    }
}