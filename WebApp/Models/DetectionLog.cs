using System;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace WebApp.Models
{
    [Table("detection_logs")]
    public class DetectionLog
    {
        [Key]
        [Column("detection_id")]
        public int DetectionId { get; set; }

        [Column("camera_id")]
        public int CameraId { get; set; }

        [Column("detection_type")]
        public string DetectionType { get; set; } = string.Empty;

        [Column("detected_count")]
        public int DetectedCount { get; set; }

        [Column("confidence")]
        public float Confidence { get; set; }

        [Column("image_path")]
        public string? ImagePath { get; set; }

        [Column("triggered_alert")]
        public bool TriggeredAlert { get; set; }

        [Column("created_at")]
        public DateTime Timestamp { get; set; } = DateTime.UtcNow;

        // ✅ ADD THIS
        [ForeignKey("CameraId")]
        public Camera? Camera { get; set; }
    }
}