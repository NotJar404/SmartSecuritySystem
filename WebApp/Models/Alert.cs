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
        // === ACCESS VERIFICATION EVENTS (Access.cshtml) ===
        UnauthorizedAccess,
        Intrusion,
        SuspiciousActivity,
        AccessDenied,
        AccessGranted,
        ForcedEntry,
        DoorEvent,
        SystemError,
        BruteForceAttempt,      // "Brute Force Attempt" from DB
        Tailgating,             // "Tailgating" from Pi FSM
        MotionDetected,         // "Motion Detected" from PIR sensor

        // === INDOOR ROOM MONITORING EVENTS (Camera monitoring) ===
        Loitering,              // Exceeded stay time (configurable per-room, default 20 min)
        OccupancyExceeded,      // Room headcount > MaxCapacity
        ExtendedStay,           // Warning: approaching stay limit (5 min before limit)
        SuspiciousIdle,         // Person present but PIR no motion for extended period
        EntranceLoitering,      // Lingering at entrance 5-10 min without RFID tap
        AfterHoursPresence      // Person in room outside operating hours
    }

    public enum SeverityLevel
    {
        INFO,
        LOW,
        WARNING,
        HIGH,
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