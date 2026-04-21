using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace WebApp.Models
{
    [Table("camera_devices")]
    public class Camera
    {
        [Key]
        [Column("camera_id")]
        public int Id { get; set; }

        [Required(ErrorMessage = "Camera name is required.")]
        [StringLength(100)]
        [Column("camera_name")]
        public string Name { get; set; } = string.Empty;

        [Required(ErrorMessage = "Room is required.")]
        [Range(1, int.MaxValue, ErrorMessage = "Please select a valid room.")]
        [Column("room_id")]
        public int RoomId { get; set; }

        [ForeignKey("RoomId")]
        public Room? Room { get; set; }

        // =========================================================
        // STREAM URL (FIXED FOR RASPBERRY PI + LOCAL TEST MODE)
        // =========================================================
        /*
         * IMPORTANT:
         * - Raspberry Pi cameras WILL use StreamUrl
         * - Local laptop webcam testing MAY NOT require StreamUrl
         *   (handled in frontend fallback using getUserMedia)
         *
         * So we REMOVE [Required] to allow flexibility
         */
        [StringLength(500)]
        [Column("stream_url")]
        public string? StreamUrl { get; set; }   // <-- FIXED (nullable but NOT required)

        [Required(ErrorMessage = "Location is required.")]
        [StringLength(100)]
        [Column("location")]
        public string Location { get; set; } = string.Empty;

        [Required]
        [StringLength(20)]
        [Column("status")]
        public string Status { get; set; } = "active";

        [NotMapped]
        public string RoomName => Room?.RoomName ?? "";
    }
}