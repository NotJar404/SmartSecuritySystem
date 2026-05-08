using System;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace WebApp.Models
{
    /// <summary>
    /// EF model for the existing 'recordings' table.
    /// Stores video evidence file paths linked to alerts.
    /// Recordings are created by the Python FSM edge controller
    /// and pushed via /Cameras/PushRecording API.
    /// </summary>
    [Table("recordings")]
    public class Recording
    {
        [Key]
        [Column("recording_id")]
        public int RecordingId { get; set; }

        [Column("camera_id")]
        public int CameraId { get; set; }

        [Column("alert_id")]
        public int? AlertId { get; set; }

        [Column("file_path")]
        public string FilePath { get; set; } = "";

        [Column("file_size_mb")]
        public double? FileSizeMb { get; set; }

        [Column("is_archived")]
        public bool IsArchived { get; set; } = false;

        [Column("timestamp")]
        public DateTime Timestamp { get; set; } = DateTime.UtcNow;

        // =========================
        // RELATIONSHIPS
        // =========================
        [ForeignKey("AlertId")]
        public Alert? Alert { get; set; }

        [ForeignKey("CameraId")]
        public Camera? Camera { get; set; }

        // =========================
        // UI HELPERS
        // =========================
        [NotMapped]
        public string FileName => System.IO.Path.GetFileName(FilePath);

        [NotMapped]
        public int MinutesAgo => (int)(DateTime.UtcNow - Timestamp).TotalMinutes;
    }
}
