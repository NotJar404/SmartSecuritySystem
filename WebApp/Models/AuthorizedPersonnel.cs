using System;
using System.Collections.Generic; // ✅ ADD THIS
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace WebApp.Models
{
    [Table("authorized_personnel")]
    public class AuthorizedPersonnel
    {
        [Key]
        [Column("person_id")]
        public int PersonId { get; set; }

        [Required]
        [Column("full_name")]
        public string FullName { get; set; } = string.Empty;

        [Required]
        [Column("rfid_tag")]
        public string RfidTag { get; set; } = string.Empty;

        [Required]
        [Column("face_embedding")]
        public string FaceEmbedding { get; set; } = string.Empty;

        [Column("department")]
        public string? Department { get; set; }

        [Column("email")]
        public string? Email { get; set; }

        [Column("phone")]
        public string? Phone { get; set; }

        [Column("profile_image_path")]
        public string? ProfileImagePath { get; set; }

        [Required]
        [Column("status")]
        public string Status { get; set; } = "active";

        [Column("security_level")]
        public string SecurityLevel { get; set; } = "normal";

        [Column("created_at")]
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

        [Column("updated_at")]
        public DateTime UpdatedAt { get; set; } = DateTime.UtcNow;

        // 🔗 THIS IS THE CONNECTION TO access_logs
        public ICollection<AccessLog>? AccessLogs { get; set; }

        // 🔗 Room-based access control
        public ICollection<PersonRoomAccess> RoomAccess { get; set; } = new List<PersonRoomAccess>();
    }
}