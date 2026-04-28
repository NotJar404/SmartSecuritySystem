using System;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace SmartSecuritySystem.Models
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

        // Matches your SQL "face_embedding" column exactly
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

        // Logic check: Matches your SQL default 'active'
        [Required]
        [Column("status")]
        public string Status { get; set; } = "active";

        // Logic check: Matches your SQL default 'normal'
        [Column("security_level")]
        public string SecurityLevel { get; set; } = "normal";

        [Column("created_at")]
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

        [Column("updated_at")]
        public DateTime UpdatedAt { get; set; } = DateTime.UtcNow;
    }
}