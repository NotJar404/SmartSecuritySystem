using System;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace WebApp.Models
{
    [Table("alerts")]
    public class Alert
    {
        [Key]
        [Column("alert_id")]
        public int AlertId { get; set; }

        [Column("type")]
        public string Type { get; set; } = string.Empty;

        [Column("description")]
        public string? Description { get; set; }

        [Column("severity")]
        public SeverityLevel Severity { get; set; } = SeverityLevel.WARNING;

        [Column("room_id")]
        public int? RoomId { get; set; }

        [Column("timestamp")]
        public DateTime Timestamp { get; set; } = DateTime.UtcNow;

        [Column("status")]
        public AlertStatus Status { get; set; } = AlertStatus.New;

        // UI ONLY
        [NotMapped]
        public int MinutesAgo => (int)(DateTime.UtcNow - Timestamp).TotalMinutes;

        [NotMapped]
        public bool IsCritical => Severity == SeverityLevel.CRITICAL;

        [NotMapped]
        public bool IsResolved => Status == AlertStatus.Resolved;

        [NotMapped]
        public bool IsActive => Status == AlertStatus.New;
    }

    public enum SeverityLevel
    {
        WARNING,
        CRITICAL
    }

    public enum AlertStatus
    {
        New,
        Acknowledged,
        Resolved
    }
}