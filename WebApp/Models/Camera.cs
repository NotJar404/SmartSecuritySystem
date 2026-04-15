using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace WebApp.Models
{
    [Table("camera_devices")]
    public class Camera
    {
        // =========================
        // PRIMARY KEY
        // =========================
        [Key]
        [Column("camera_id")]
        public int Id { get; set; }

        // =========================
        // CAMERA NAME
        // =========================
        [Required(ErrorMessage = "Camera name is required.")]
        [StringLength(100)]
        [Column("camera_name")]
        public string Name { get; set; } = string.Empty;

        // =========================
        // ROOM ID (FIXED ✅)
        // =========================
        // 🔥 Changed from int? → int (CRITICAL FIX)
        [Required(ErrorMessage = "Room is required.")]
        [Range(1, int.MaxValue, ErrorMessage = "Please select a valid room.")]
        [Column("room_id")]
        public int RoomId { get; set; }

        // Navigation Property
        [ForeignKey("RoomId")]
        public Room? Room { get; set; }

        // =========================
        // STREAM URL
        // =========================
        [Required(ErrorMessage = "Stream URL is required.")]
        [StringLength(500)]
        [Column("stream_url")]
        public string StreamUrl { get; set; } = string.Empty;

        // =========================
        // LOCATION
        // =========================
        [Required(ErrorMessage = "Location is required.")]
        [StringLength(100)]
        [Column("location")]
        public string Location { get; set; } = string.Empty;

        // =========================
        // STATUS
        // =========================
        [Required]
        [StringLength(20)]
        [Column("status")]
        public string Status { get; set; } = "active";

        // =========================
        // DISPLAY ONLY
        // =========================
        [NotMapped]
        public string RoomName => Room?.RoomName ?? "";
    }
}