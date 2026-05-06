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

        // Stored as STRING in DB
        [Column("type")]
        public AlertType Type { get; set; }

        [Column("description")]
        public string? Description { get; set; }

        // Stored as STRING in DB
        [Column("severity")]
        public SeverityLevel Severity { get; set; } = SeverityLevel.WARNING;

        // =========================
        // ROOM RELATIONSHIP (FIXED)
        // =========================

        [Column("room_id")]
        public int? RoomId { get; set; }

        [ForeignKey("RoomId")]
        public Room? Room { get; set; }

        // =========================
        // TIMESTAMP
        // =========================

        [Column("timestamp")]
        public DateTime Timestamp { get; set; } = DateTime.UtcNow;

        // Stored as STRING in DB
        [Column("status")]
        public AlertStatus Status { get; set; } = AlertStatus.New;

        // =========================
        // RECORDING LINK
        // =========================

        [Column("video_path")]
        public string? VideoPath { get; set; }

        // =========================
        // TRACKING & ACCOUNTABILITY
        // =========================

        [Column("acknowledged_by")]
        public string? AcknowledgedBy { get; set; }

        [Column("acknowledged_at")]
        public DateTime? AcknowledgedAt { get; set; }

        [Column("resolved_by")]
        public string? ResolvedBy { get; set; }

        [Column("resolved_at")]
        public DateTime? ResolvedAt { get; set; }

        [Column("escalated_by")]
        public string? EscalatedBy { get; set; }

        [Column("escalated_at")]
        public DateTime? EscalatedAt { get; set; }

        // =========================
        // UI HELPERS (NOT IN DB)
        // =========================

        [NotMapped]
        public int MinutesAgo => (int)(DateTime.UtcNow - Timestamp).TotalMinutes;

        [NotMapped]
        public bool IsCritical => Severity == SeverityLevel.CRITICAL;

        [NotMapped]
        public bool IsResolved => Status == AlertStatus.Resolved;

        [NotMapped]
        public bool IsActive => Status != AlertStatus.Resolved;

        [NotMapped]
        public bool HasRecording => !string.IsNullOrEmpty(VideoPath);
    }

    // =========================
    // ENUMS
    // =========================

    public enum AlertType
    {
        UnauthorizedAccess,
        Intrusion,
        SuspiciousActivity,
        AccessDenied,
        AccessGranted,
        ForcedEntry,
        DoorEvent,
        SystemError
    }

    public enum SeverityLevel
    {
        INFO,
        WARNING,
        CRITICAL
    }

    public enum AlertStatus
    {
        New,
        Acknowledged,
        Escalated,
        Resolved
    }
}