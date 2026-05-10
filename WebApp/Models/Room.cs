using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace WebApp.Models
{
    [Table("rooms")]
    public class Room
    {
        [Key]
        [Column("room_id")]
        public int RoomId { get; set; }

        [Required]
        [Column("room_name")]
        [StringLength(100)]
        public string RoomName { get; set; } = string.Empty;

        // OPTIONAL (recommended for occupancy feature)
        [Column("description")]
        public string? Description { get; set; }

        // OPTIONAL (VERY GOOD FOR YOUR SYSTEM)
        [Column("max_capacity")]
        public int? MaxCapacity { get; set; }

        // Navigation properties
        public ICollection<CameraDevice> Cameras { get; set; } = new List<CameraDevice>();

        public ICollection<RoomOccupancy> OccupancyLogs { get; set; } = new List<RoomOccupancy>();

        // Room-based access control
        public ICollection<PersonRoomAccess> PersonAccess { get; set; } = new List<PersonRoomAccess>();
    }
}